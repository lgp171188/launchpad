# Copyright 2013-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper methods to search specifications."""

__all__ = [
    "get_specification_filters",
    "get_specification_active_product_filter",
    "get_specification_privacy_filter",
    "search_specifications",
]

from collections import defaultdict
from functools import reduce

from storm.expr import (
    And,
    Coalesce,
    Column,
    Join,
    LeftJoin,
    Not,
    Or,
    Select,
    Table,
    Union,
)
from storm.locals import SQL, Desc
from zope.component import getUtility

from lp.app.enums import PUBLIC_INFORMATION_TYPES
from lp.blueprints.enums import (
    SpecificationDefinitionStatus,
    SpecificationFilter,
    SpecificationGoalStatus,
    SpecificationImplementationStatus,
    SpecificationSort,
)
from lp.blueprints.model.specification import Specification
from lp.blueprints.model.specificationbranch import SpecificationBranch
from lp.blueprints.model.specificationworkitem import SpecificationWorkItem
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.role import IPersonRoles
from lp.registry.model.teammembership import TeamParticipation
from lp.services.database.bulk import load_referencing
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import (
    Array,
    ArrayAgg,
    ArrayIntersects,
    WithMaterialized,
    fti_search,
)
from lp.services.propertycache import get_property_cache


def search_specifications(
    context,
    base_clauses,
    user,
    sort=None,
    quantity=None,
    spec_filter=None,
    tables=[],
    default_acceptance=False,
    need_people=True,
    need_branches=True,
    need_workitems=False,
    base_id_clauses=None,
):
    store = IStore(Specification)
    if not default_acceptance:
        default = SpecificationFilter.INCOMPLETE
        options = {
            SpecificationFilter.COMPLETE,
            SpecificationFilter.INCOMPLETE,
        }
    else:
        default = SpecificationFilter.ACCEPTED
        options = {
            SpecificationFilter.ACCEPTED,
            SpecificationFilter.DECLINED,
            SpecificationFilter.PROPOSED,
        }
    if not spec_filter:
        spec_filter = [default]

    if not set(spec_filter) & options:
        spec_filter.append(default)

    if not tables:
        tables = [Specification]
    product_tables, product_clauses = get_specification_active_product_filter(
        context
    )
    tables.extend(product_tables)

    # If there are any base clauses, they typically have good selectivity,
    # so use a CTE to force PostgreSQL to calculate them up-front rather
    # than doing a sequential scan for visible specifications.
    if base_clauses or base_id_clauses:
        RelevantSpecification = Table("RelevantSpecification")
        # Base ID clauses (that is, those that search for specifications
        # whose IDs are in a set computed by a subquery) pose an
        # optimization problem.  If we include them in a disjunction with
        # other clauses that search for well-indexed columns such as the
        # owner, then rather than using each of the appropriate indexes and
        # combining them, the PostgreSQL planner will perform a sequential
        # scan over the whole Specification table.  To avoid this, we put
        # such clauses in a separate query and UNION them together.
        relevant_specification_cte = WithMaterialized(
            RelevantSpecification.name,
            store,
            Union(
                *(
                    Select(
                        Specification.id,
                        And(clauses + product_clauses),
                        tables=tables,
                    )
                    for clauses in (base_clauses, base_id_clauses)
                    if clauses
                )
            ),
        )
        store = store.with_(relevant_specification_cte)
        tables = [
            Specification,
            Join(
                RelevantSpecification,
                Specification.id == Column("id", RelevantSpecification),
            ),
        ]
        clauses = []
    else:
        clauses = list(product_clauses)

    clauses.extend(get_specification_privacy_filter(user))
    clauses.extend(get_specification_filters(spec_filter))

    # Sort by priority descending, by default.
    if sort is None or sort == SpecificationSort.PRIORITY:
        order = [
            Desc(Specification.priority),
            Specification.definition_status,
            Specification.name,
        ]
    elif sort == SpecificationSort.DATE:
        if SpecificationFilter.COMPLETE in spec_filter:
            # If we are showing completed, we care about date completed.
            order = [Desc(Specification.date_completed), Specification.id]
        else:
            # If not specially looking for complete, we care about date
            # registered.
            order = []
            show_proposed = {
                SpecificationFilter.ALL,
                SpecificationFilter.PROPOSED,
            }
            if default_acceptance and not (set(spec_filter) & show_proposed):
                order.append(Desc(Specification.date_goal_decided))
            order.extend([Desc(Specification.datecreated), Specification.id])
    else:
        order = [sort]

    # Set the _known_viewers property for each specification, as well as
    # preloading the objects involved, if asked.
    def preload_hook(rows):
        person_ids = set()
        work_items_by_spec = defaultdict(list)
        for spec in rows:
            if need_people:
                person_ids |= {
                    spec._assignee_id,
                    spec._approver_id,
                    spec._drafter_id,
                }
            if need_branches:
                get_property_cache(spec).linked_branches = []
        if need_workitems:
            work_items = load_referencing(
                SpecificationWorkItem,
                rows,
                ["specification_id"],
                extra_conditions=[SpecificationWorkItem.deleted == False],
            )
            for workitem in work_items:
                person_ids.add(workitem.assignee_id)
                work_items_by_spec[workitem.specification_id].append(workitem)
        person_ids -= {None}
        if need_people:
            list(
                getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                    person_ids, need_validity=True
                )
            )
        if need_workitems:
            for spec in rows:
                get_property_cache(spec).work_items = sorted(
                    work_items_by_spec[spec.id], key=lambda wi: wi.sequence
                )
        if need_branches:
            spec_branches = load_referencing(
                SpecificationBranch, rows, ["specification_id"]
            )
            for sbranch in spec_branches:
                spec_cache = get_property_cache(sbranch.specification)
                spec_cache.linked_branches.append(sbranch)

    decorators = []
    if user is not None and not IPersonRoles(user).in_admin:
        decorators.append(_make_cache_user_can_view_spec(user))
    results = (
        store.using(*tables)
        .find(Specification, *clauses)
        .order_by(*order)
        .config(limit=quantity)
    )
    return DecoratedResultSet(
        results,
        lambda row: reduce(lambda task, dec: dec(task), decorators, row),
        pre_iter_hook=preload_hook,
    )


def get_specification_active_product_filter(context):
    if (
        IDistribution.providedBy(context)
        or IDistroSeries.providedBy(context)
        or IProduct.providedBy(context)
        or IProductSeries.providedBy(context)
    ):
        return [], []
    from lp.registry.model.product import Product

    tables = [LeftJoin(Product, Specification.product_id == Product.id)]
    active_products = Or(Specification.product == None, Product.active == True)
    return tables, [active_products]


def get_specification_privacy_filter(user):
    # Circular imports.
    from lp.registry.model.accesspolicy import AccessPolicyGrant

    public_spec_filter = Specification.information_type.is_in(
        PUBLIC_INFORMATION_TYPES
    )

    if user is None:
        return [public_spec_filter]
    elif IPersonRoles.providedBy(user):
        user = user.person

    artifact_grant_query = Coalesce(
        ArrayIntersects(
            SQL("Specification.access_grants"),
            Select(
                ArrayAgg(TeamParticipation.team_id),
                tables=TeamParticipation,
                where=(TeamParticipation.person == user),
            ),
        ),
        False,
    )

    policy_grant_query = Coalesce(
        ArrayIntersects(
            Array(SQL("Specification.access_policy")),
            Select(
                ArrayAgg(AccessPolicyGrant.policy_id),
                tables=(
                    AccessPolicyGrant,
                    Join(
                        TeamParticipation,
                        TeamParticipation.team_id
                        == AccessPolicyGrant.grantee_id,
                    ),
                ),
                where=(TeamParticipation.person == user),
            ),
        ),
        False,
    )

    return [Or(public_spec_filter, artifact_grant_query, policy_grant_query)]


def get_specification_filters(filter, goalstatus=True):
    """Return a list of Storm expressions for filtering Specifications.

    :param filters: A collection of SpecificationFilter and/or strings.
        Strings are used for text searches.
    """
    clauses = []
    # ALL is the trump card.
    if SpecificationFilter.ALL in filter:
        return clauses
    # Look for informational specs.
    if SpecificationFilter.INFORMATIONAL in filter:
        clauses.append(
            Specification.implementation_status
            == SpecificationImplementationStatus.INFORMATIONAL
        )
    # Filter based on completion.  See the implementation of
    # Specification.is_complete() for more details.
    if SpecificationFilter.COMPLETE in filter:
        clauses.append(get_specification_completeness_clause())
    if SpecificationFilter.INCOMPLETE in filter:
        clauses.append(Not(get_specification_completeness_clause()))

    # Filter for goal status.
    if goalstatus:
        goalstatus = None
        if SpecificationFilter.ACCEPTED in filter:
            goalstatus = SpecificationGoalStatus.ACCEPTED
        elif SpecificationFilter.PROPOSED in filter:
            goalstatus = SpecificationGoalStatus.PROPOSED
        elif SpecificationFilter.DECLINED in filter:
            goalstatus = SpecificationGoalStatus.DECLINED
        if goalstatus:
            clauses.append(Specification.goalstatus == goalstatus)

    if SpecificationFilter.STARTED in filter:
        clauses.append(get_specification_started_clause())

    # Filter for validity. If we want valid specs only, then we should exclude
    # all OBSOLETE or SUPERSEDED specs.
    if SpecificationFilter.VALID in filter:
        clauses.append(
            Not(
                Specification.definition_status.is_in(
                    [
                        SpecificationDefinitionStatus.OBSOLETE,
                        SpecificationDefinitionStatus.SUPERSEDED,
                    ]
                )
            )
        )
    # Filter for specification text.
    for constraint in filter:
        if isinstance(constraint, str):
            # A string in the filter is a text search filter.
            clauses.append(fti_search(Specification, constraint))
    return clauses


def _make_cache_user_can_view_spec(user):
    userid = user.id

    def cache_user_can_view_spec(spec):
        get_property_cache(spec)._known_viewers = {userid}
        return spec

    return cache_user_can_view_spec


def get_specification_started_clause():
    return Or(
        Not(
            Specification.implementation_status.is_in(
                [
                    SpecificationImplementationStatus.UNKNOWN,
                    SpecificationImplementationStatus.NOTSTARTED,
                    SpecificationImplementationStatus.DEFERRED,
                    SpecificationImplementationStatus.INFORMATIONAL,
                ]
            )
        ),
        And(
            Specification.implementation_status
            == SpecificationImplementationStatus.INFORMATIONAL,
            Specification.definition_status
            == SpecificationDefinitionStatus.APPROVED,
        ),
    )


def get_specification_completeness_clause():
    return Or(
        Specification.implementation_status
        == SpecificationImplementationStatus.IMPLEMENTED,
        Specification.definition_status.is_in(
            [
                SpecificationDefinitionStatus.OBSOLETE,
                SpecificationDefinitionStatus.SUPERSEDED,
            ]
        ),
        And(
            Specification.implementation_status
            == SpecificationImplementationStatus.INFORMATIONAL,
            Specification.definition_status
            == SpecificationDefinitionStatus.APPROVED,
        ),
    )
