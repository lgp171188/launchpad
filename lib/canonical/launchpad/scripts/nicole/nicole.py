#!/usr/bin/env python
from string import split
from time import sleep
from sys import argv, exit
from re import sub
from sourceforge import getProductSpec
from database import Doap
from datetime import datetime

from apt_pkg import ParseTagFile

import tempfile, os

## DOAP is inside our current Launchpad production DB
DOAPDB = "launchpad_dev"

package_root = "/ubuntu/"
distrorelease = "hoary"
component = "main"


## Web search interval avoiding to be blocked by high threshould
## of requests reached by second
SLEEP = 20

## Entries not found
LIST = 'nicole_notfound'

sf = 0
fm = 0
both = 0
skip = 0

def clean_list():
    print """Cleaning 'Not Found' File List"""
    f = open(LIST, 'w')
    timestamp = datetime.isoformat(datetime.utcnow())
    f.write('Generated by Nicole at UTC %s\n' % timestamp)
    f.close()

def append_list(data):
    print """@\tAppending %s in 'Not Found' File List""" % data
    f = open(LIST, 'a')
    f.write('%s\n' % data)
    f.close()

def get_current_packages():
    packagenames = []

    print '@ Retrieve SourcePackage Information From Soyuz'

    index = 0
    
    ## Get SourceNames from Sources file (MAIN)
    sources_zipped = os.path.join(package_root, "dists", distrorelease,
                                  component, "source", "Sources.gz")
    srcfd, sources_tagfile = tempfile.mkstemp()
    os.system("gzip -dc %s > %s" % (sources_zipped,
                                    sources_tagfile)) 
    sources = ParseTagFile(os.fdopen(srcfd))
    while sources.Step():        
        packagenames.append(sources.Section['Package'])
        index += 1

    print '@ %d SourcePackages from Soyuz' % index        
    return index, packagenames


def grab_web_info(name):
    print '@ Looking for %s on Sourceforge' % name    
    try:
        data_sf = getProductSpec(name)
        print '@\tFound at Sourceforge'        
    except:
        print '@\tNot Found'
        data_sf = None

    print '@ Looking for %s on FreshMeat' % name        
    try:
        data_fm = getProductSpec(name, 'fm')
        print '@\tFound at FreshMeat'
    except:
        print '@\tNot Found'
        data_fm = None
            
    return data_sf, data_fm

def inserter(doap, product_name):
    global fm, sf, both

    data_sf, data_fm = grab_web_info(product_name)

    if data_sf and not data_fm:
        sf +=1            
        doap.ensureProduct(data_sf, product_name, None)
    elif data_fm and not data_sf:
        fm += 1
        doap.ensureProduct(data_fm, product_name, None)
    elif data_sf and data_fm:
        both += 1
        ##XXX: cprov
        ##Do we really preffer sourceforge ???
        doap.ensureProduct(data_sf, None)
    else:
        print '@\tNo Product Found for %s' % product_name
        append_list(product_name)                


if __name__ == "__main__":
    # get the DB abstractors
    doap = Doap(DOAPDB)

    if len(argv) > 1:
        mode = argv[1][1:]
    else:
        mode = 'h'

    print '\tNicole: Product Information Finder'
        
    index = 0
    clean_list()
    
    if len(argv) > 1:
        f = open(argv[1], 'r')
        products = f.read().strip().split('\n')
        print products
        tries = len(products)
    else:
        tries, products = doap.getProductsForUpdate()
        print products

    for product in products:
        index += 1
        print ' '
        print '@ Grabbing Information About the %s (%d/%d)'% (product,
                                                              index,
                                                              tries)
        inserter(doap, product)
        ## Partially Commit DB Product Info
        doap.commit()            
        ##It should prevent me to be blocked again by SF
        sleep(SLEEP)
           
        
    fail = tries - (sf + fm + both + skip)

    doap.close()

    print '@\t\tSourceforge (only) %d' % sf
    print '@\t\tFreshMeat (only)   %d' % fm
    print '@\t\tBoth               %d' % both
    print '@\t\tFailures           %d' % fail
    print '@\t\tSkips:             %d' % skip
    print '@\t\tTries:             %d' % tries
    print '@ Thanks for using Nicole'
