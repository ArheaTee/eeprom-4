# ------------------------------------------------------------------------------
# Palomar CM Test Plan
# CM creates some function in this place
# by Chaitud, 23-Feb-2018
# ------------------------------------------------------------------------------

import shutil, os, time, urllib2
import glob, os.path
import csv
#import requests

print "=========================================================="
print "          Welcome to Palomar CM Test Plan                 "
print "=========================================================="
print time.ctime()
#desProfile = "http://10.196.100.17/des/ELM/getparameter.asp?sn=PRCCTH180700043&profile=CONTROL_MACID&MACID=08:9E:08:E8:F4:E9"
    
def checkMac(sn, mac):
    cthMes45 = "http://10.196.100.17/des/ELM/getparameter.asp?sn="
    profileMac = "&profile=CONTROL_MACID&MACID="
    desProfile = cthMes45+sn+profileMac+mac
    print "Sending:",cthMes45,sn,profileMac,mac
    readProfile =  urllib2.urlopen(desProfile)
    macCheck = readProfile.read()
    print macCheck
    if macCheck == "OK":
        return True
    else:
         prompt = "Mac address duplicate"
         return False
       
#Added 16-Oct-2018 for check current station
def checkStation(sn, stn):
    desurl = "http://10.196.100.17/des/elm/getparameter.asp?profile=CURR_STATION&SN="
    stndesProfile = desurl+sn
    print "Sending:",stndesProfile
    readProfile =  urllib2.urlopen(desProfile)
    stnCheck = readProfile.read()
    if stnCheck == "510008":
        return True
    else:
        prompt = "Wrong Station"
        return False
    