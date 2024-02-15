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
odc_server = ["10.196.100.17", "10.196.100.16"]

def checkStation(sn):
    #cthMes45 = "http://10.196.100.17/des/elm/getparameter.asp?profile=CURR_STATION&SN="
                            
    odc_flag = False
    odc_enable = False #Teera
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
        
        currentStation = ODCTest.getCurrentStation(sn)
        print currentStation
        if currentStation == "520036":
            msg = "Correct station"
            return True, msg
        else:
             msg = "Wrong Station\nCurrent Station: " + currentStation
             return False, msg
    else:
        msg = ""
        return True, msg
        
def checkTlaSn(pcbaSN,TlaLabelSN):
        #https://ehd.celestica.com/usercontrol/commentactionallpage.aspx?id=ehdb00001094638
        #how it works. send pcba sn --> profile return tla sn
    odc_flag = True
    odc_enable =  True  #Teera
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
        
        odcTlaSn = ODCTest.getTlaSn(pcbaSN)
        print ">>>TLA SN from ODC is:", odcTlaSn
        if odcTlaSn == TlaLabelSN:
            msg = ">>> TLA & PCBA are match"
            return True , msg 
        else:
             msg = ">>> Wrong assembly", TlaLabelSN, odcTlaSn
             return False, msg
    else:
        msg = ""
        return True, msg
        
        