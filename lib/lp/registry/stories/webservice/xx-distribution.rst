Distributions
=============

At the top level we provide the collection of all distributions, with
Ubuntu and its flavours being the first on the list.

    >>> distros = webservice.get("/distros").jsonBody()
    >>> for entry in distros["entries"]:
    ...     print(entry["self_link"])
    ...
    http://.../ubuntu
    http://.../kubuntu
    http://.../ubuntutest
    http://.../debian
    http://.../gentoo

And for every distribution we publish most of its attributes.

    >>> from lazr.restful.testing.webservice import pprint_entry
    >>> distro = distros["entries"][0]
    >>> ubuntu = webservice.get(distro["self_link"]).jsonBody()
    >>> pprint_entry(ubuntu)
    active: True
    active_milestones_collection_link: 'http://.../ubuntu/active_milestones'
    all_milestones_collection_link: 'http://.../ubuntu/all_milestones'
    archive_mirrors_collection_link: 'http://.../ubuntu/archive_mirrors'
    archives_collection_link: 'http://.../ubuntu/archives'
    bug_reported_acknowledgement: None
    bug_reporting_guidelines: None
    bug_supervisor_link: None
    cdimage_mirrors_collection_link: 'http://.../ubuntu/cdimage_mirrors'
    code_admin_link: None
    commercial_subscription_is_due: False
    commercial_subscription_link: None
    content_templates: None
    current_series_link: 'http://.../ubuntu/hoary'
    date_created: '2006-10-16T18:31:43.415195+00:00'
    default_traversal_policy: 'Series'
    derivatives_collection_link: 'http://.../ubuntu/derivatives'
    description: 'Ubuntu is a new approach...'
    development_series_alias: None
    display_name: 'Ubuntu'
    domain_name: 'ubuntulinux.org'
    driver_link: None
    homepage_content: None
    icon_link: 'http://.../ubuntu/icon'
    information_type: 'Public'
    logo_link: 'http://.../ubuntu/logo'
    main_archive_link: 'http://.../ubuntu/+archive/primary'
    members_link: 'http://.../~ubuntu-team'
    mirror_admin_link: 'http://.../~ubuntu-mirror-admins'
    mugshot_link: 'http://.../ubuntu/mugshot'
    name: 'ubuntu'
    oci_project_admin_link: None
    official_answers: True
    official_blueprints: True
    official_bug_tags: []
    official_bugs: True
    official_codehosting: False
    official_packages: True
    owner_link: 'http://.../~ubuntu-team'
    private: False
    redirect_default_traversal: False
    redirect_release_uploads: False
    registrant_link: 'http://.../~registry'
    resource_type_link: 'http://.../#distribution'
    security_admin_link: None
    self_link: 'http://.../ubuntu'
    series_collection_link: 'http://.../ubuntu/series'
    summary: 'Ubuntu is a new approach to Linux Distribution...'
    supports_mirrors: True
    supports_ppas: True
    title: 'Ubuntu'
    vcs: None
    vulnerabilities_collection_link: 'http://.../ubuntu/vulnerabilities'
    web_link: 'http://launchpad.../ubuntu'
    webhooks_collection_link: 'http://api.launchpad.../ubuntu/webhooks'


Distribution Custom Operations
==============================

Distribution has some custom operations.

"getSeries" returns the named distribution series for the distribution.

    >>> series = webservice.named_get(
    ...     ubuntu["self_link"], "getSeries", name_or_version="hoary"
    ... ).jsonBody()
    >>> print(series["self_link"])
    http://.../ubuntu/hoary

Requesting a series that does not exist is results in a not found error.

    >>> print(
    ...     webservice.named_get(
    ...         ubuntu["self_link"], "getSeries", name_or_version="fnord"
    ...     )
    ... )
    HTTP/1.1 404 Not Found
    ...
    No such distribution series: 'fnord'.

"getDevelopmentSeries" returns all the distribution series for the
distribution that are marked as in development.

    >>> dev_series = webservice.named_get(
    ...     ubuntu["self_link"], "getDevelopmentSeries"
    ... ).jsonBody()
    >>> for entry in sorted(dev_series["entries"]):
    ...     print(entry["self_link"])
    ...
    http://.../ubuntu/hoary

"getMilestone" returns a milestone for the given name, or None if there
is no milestone for the given name.

    >>> distro = distros["entries"][3]
    >>> debian = webservice.get(distro["self_link"]).jsonBody()

    >>> milestone_3_1 = webservice.named_get(
    ...     debian["self_link"], "getMilestone", name="3.1"
    ... ).jsonBody()
    >>> print(milestone_3_1["self_link"])
    http://.../debian/+milestone/3.1

    >>> print(
    ...     webservice.named_get(
    ...         debian["self_link"], "getMilestone", name="fnord"
    ...     ).jsonBody()
    ... )
    None

"getSourcePackage" returns a distribution source package for the given
name.

    >>> alsa_utils = webservice.named_get(
    ...     ubuntu["self_link"], "getSourcePackage", name="alsa-utils"
    ... ).jsonBody()
    >>> print(alsa_utils["self_link"])
    http://.../ubuntu/+source/alsa-utils

"searchSourcePackages" returns a collection of distribution source
packages matching (substring) the given text.

    >>> alsa_results = webservice.named_get(
    ...     ubuntu["self_link"], "searchSourcePackages", source_match="a"
    ... ).jsonBody()

    >>> for entry in alsa_results["entries"]:
    ...     print(entry["self_link"])
    ...
    http://.../ubuntu/+source/alsa-utils
    http://.../ubuntu/+source/commercialpackage
    http://.../ubuntu/+source/foobar
    http://.../ubuntu/+source/mozilla-firefox
    http://.../ubuntu/+source/netapplet

"getArchive" returns a distribution archive (not a PPA) with the given name.

    >>> partner = webservice.named_get(
    ...     ubuntu["self_link"], "getArchive", name="partner"
    ... ).jsonBody()
    >>> print(partner["self_link"])
    http://.../ubuntu/+archive/partner

"getMirrorByName" returns a mirror by its unique name.

    >>> canonical_releases = webservice.named_get(
    ...     ubuntu["self_link"], "getMirrorByName", name="canonical-releases"
    ... ).jsonBody()
    >>> pprint_entry(canonical_releases)
    base_url: 'http://releases.ubuntu.com/'
    content: 'CD Image'
    country_dns_mirror: False
    country_link: 'http://.../+countries/GB'
    date_created: '2006-10-16T18:31:43.434567+00:00'
    date_reviewed: None
    description: None
    displayname: None
    distribution_link: 'http://.../ubuntu'
    enabled: True
    ftp_base_url: None
    http_base_url: 'http://releases.ubuntu.com/'
    https_base_url: None
    name: 'canonical-releases'
    official_candidate: True
    owner_link: 'http://.../~mark'
    resource_type_link: 'http://.../#distribution_mirror'
    reviewer_link: None
    rsync_base_url: None
    self_link: 'http://.../ubuntu/+mirror/canonical-releases'
    speed: '100 Mbps'
    status: 'Official'
    web_link: 'http://launchpad.../ubuntu/+mirror/canonical-releases'
    whiteboard: None

"getCountryMirror" returns the country DNS mirror for a given country;
returning None if there isn't one.

Prepare stuff.

    >>> import json
    >>> from zope.component import getUtility
    >>> from lp.testing.pages import webservice_for_person
    >>> from lp.services.webapp.interfaces import OAuthPermission
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.person import IPersonSet

    >>> login("admin@canonical.com")
    >>> ubuntu_distro = getUtility(IDistributionSet).getByName("ubuntu")
    >>> showa_station = factory.makeMirror(
    ...     ubuntu_distro,
    ...     "Showa Station",
    ...     country=9,
    ...     http_url="http://mirror.showa.antarctica.org/ubuntu",
    ...     official_candidate=True,
    ... )
    >>> showa_station_log = factory.makeMirrorProbeRecord(showa_station)

    >>> login(ANONYMOUS)
    >>> karl_db = getUtility(IPersonSet).getByName("karl")
    >>> karl_webservice = webservice_for_person(
    ...     karl_db, permission=OAuthPermission.WRITE_PUBLIC
    ... )
    >>> logout()

Mark new mirror as official and a country mirror.

    >>> patch = {"status": "Official", "country_dns_mirror": True}

    >>> antarctica_patch_target = webservice.named_get(
    ...     ubuntu["self_link"],
    ...     "getMirrorByName",
    ...     name="mirror.showa.antarctica.org-archive",
    ... ).jsonBody()

    >>> response = karl_webservice.patch(
    ...     antarctica_patch_target["self_link"],
    ...     "application/json",
    ...     json.dumps(patch),
    ... )

    >>> antarctica = webservice.get("/+countries/AQ").jsonBody()
    >>> antarctica_country_mirror_archive = webservice.named_get(
    ...     ubuntu["self_link"],
    ...     "getCountryMirror",
    ...     country=antarctica["self_link"],
    ...     mirror_type="Archive",
    ... ).jsonBody()
    >>> pprint_entry(antarctica_country_mirror_archive)
    base_url: 'http://mirror.showa.antarctica.org/ubuntu/'
    content: 'Archive'
    country_dns_mirror: True
    country_link: 'http://.../+countries/AQ'
    ...

    >>> uk = webservice.get("/+countries/GB").jsonBody()
    >>> uk_country_mirror_archive = webservice.named_get(
    ...     ubuntu["self_link"],
    ...     "getCountryMirror",
    ...     country=uk["self_link"],
    ...     mirror_type="Archive",
    ... )
    >>> print(uk_country_mirror_archive.jsonBody())
    None

For "getCountryMirror", the mirror_type parameter must be "Archive" or
"CD Images":

    >>> uk_country_mirror_archive = webservice.named_get(
    ...     ubuntu["self_link"],
    ...     "getCountryMirror",
    ...     country=uk["self_link"],
    ...     mirror_type="Bogus",
    ... )
    >>> print(uk_country_mirror_archive.jsonBody())
    Traceback (most recent call last):
    ...
    ValueError: mirror_type: Invalid value "Bogus". Acceptable values are:
      Archive, CD Image
