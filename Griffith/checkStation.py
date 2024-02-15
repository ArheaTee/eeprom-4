# ------------------------------------------------------------------------------
# Palomar CM Test Plan
# CM creates some function in this place
# by Chaitud, 16-Oct-2018
# ------------------------------------------------------------------------------

import shutil, os, time, urllib2
import glob, os.path
import csv
import os
from ODCServer import ODCServer
import InputDialog

#print "=========================================================="
#print "          Welcome to Palomar CM Test Plan                 "
#print "=========================================================="
#print time.ctime()
#http://10.196.100.17/des/elm/getparameter.asp?profile=CURR_STATION&SN=PSMCTH184000139


def checkStation(sn):
    #cthMes45 = "http://10.196.100.17/des/elm/getparameter.asp?profile=CURR_STATION&SN="
    #desProfile = cthMes45+sn
    #print "Sending:",cthMes45,sn
    #readProfile =  urllib2.urlopen(desProfile)
    #cuStation = readProfile.read()
    #print cuStation
                            
    odc_flag = True
    odc_enable = True
    odc_server = ["10.196.100.17", "10.196.100.16"]
    if odc_enable:
        for server in odc_server:
            print server
            ODCTest = ODCServer(server, "elm")
            ODCTest.connect()
            odc_status = ODCTest.check_connection()
            if odc_status:
                odc_flag = True
                break
                
        if not odc_flag:
            msg = "ODC Server down!!!"
            return False, msg
        
        cuStation = ODCTest.getCurrentStation(sn)
        print cuStation
        if (cuStation == "520036" or "611050"):
            msg = ""
            return True, msg
        else:
             msg = "Wrong Station\nCurrent Station: " + cuStation
             return False, msg
    else:
        msg = ""
        return True, msg
    
