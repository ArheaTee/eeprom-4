# !/usr/bin/env python

import time

from server.ProcessObjects import ProcessStepResult
from server.ProcessObjects import ProcessStatus
from server.ProcessObjects import Measurement
from server.ProcessObjects import OperatorInputPromptType
from server.CriticalSectionManager import CriticalSectionTimeoutException
from server.processPlan import ProcessPlan
from server.processStep import ProcessStep
from otlibs.utils import macaddress
from otlibs.utils import pinger
import traceback
import os.path
from TestSyncronization import syncronize, syncRunSingle, syncRunSerialized, SyncObject
from PowerControl import setPowerRelayState, getPowerOnDuration
import re
import logging
import datetime
import time
import shutil
import os
import threading
import InputDialog
import EEPROM_FRU
import math
import json
import ConfigParser
import checkStation as ck_stn

PROCESS_STEP = 'FRU'
LOGGER_NAME = 'Palomar'
STATION_NAME = 'EEPROM-' + PROCESS_STEP
LOG_FILE_DIR = 'C:/'+STATION_NAME+'-LOG'
VERSION = '0.6'

HARDWARE_REVISION = "0a"
HALE_LOW_VOLTAGE_MARGIN = "0001ff"
HALE_HIGH_VOLTAGE_MARGIN = "00010c"
HALE_NOMINAL_VOLTAGE_MARGIN = "000194"

PN_PATTERN = re.compile(r"^\d{10}[0-9A-F]{2}")
ASSEMBLY_PN_PATTERN = re.compile(r"^\d{10}[0-9A-F]{2}")
MAC_PATTERN = re.compile(r"^[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}:[0-9A-F]{2}$", re.I)

#Restrict test to new Hales
EXPECTED_HALE_PN = ""

runningStationCount = 0
fh = None

def addParametricResult( step, name, value, units, upper, lower ):
    inLimits = (value >= lower) and (value <= upper)
    
    if inLimits:
        status = ProcessStatus.PASSED
    else:
        status = ProcessStatus.FAILED
    
    step.add_measurement(Measurement(name, value, units, True, True, upper, lower,status))
    
    if not inLimits:
        if isinstance(value,str):
            step.set_fail( type(step).__name__, "%s outside limits.  Measured: %s (ll: %s, ul: %s)" % (name,value, lower, upper) )
        else:
            step.set_fail( type(step).__name__, "%s outside limits.  Measured: %f (ll: %f, ul: %f)" % (name,value, lower, upper) )
        
    return inLimits



def getRunningStations(processStep):

    stations = []

    for station in processStep._process_plan._global_execution_context['process_stations'][1:]:
        if not station.is_running:
            continue
        stations.append(station)

    return stations

def log_logfile_debugoutput(self, log_msg):
    logger = logging.getLogger(LOGGER_NAME)
    logger.debug(log_msg)  # log file
    self.log(log_msg)      # OT Debug Output

class ReportProcessStep(ProcessStep):
    def run(self,):

        self.add_measurement(Measurement("Process Step",STATION_NAME,"", False, False, "", "",ProcessStatus.PASSED))

        self.set_pass()
        return ProcessStatus.PASSED

class GetEmployeeNumber(ProcessStep):
    @syncRunSingle
    def run(self,):                            
               
        config_name = "en_authorize.cfg"
        prompt = "Enter Employee Number"
        message=prompt        
        while True:           
            
            employeeNumber = InputDialog.GetOperatorInput("Employee Number",prompt).strip()
            
            try:                
                self._config = ConfigParser.RawConfigParser()            
                if not self._config.read(os.path.join(os.path.dirname(os.path.realpath(__file__)),  config_name)):
                    self.set_fail("Failed to open/parse '%s'" % config_name, "Failed to open/parse '%s'" % config_name)
                    return ProcessStatus.FAILED                    
            except Exception, ex:
                self.set_fail("Failed to open/parse '%s'" % config_name, traceback.format_exc())
                return ProcessStatus.FAILED            
            
            if not employeeNumber:
                continue
            
            try:
                authorized = True
                employee_name = self._config.get( "AllowSequenceRun", employeeNumber )
            except Exception, ex:
                authorized = False
            
            if authorized:
                break
            else:
                prompt = "Employee '%s' not authorized to run sequence\n%s" % (employeeNumber, message)
            
        self._process_plan._global_execution_context['app_config']. \
            set('Global', 'operatorName', employeeNumber)

        self.set_pass()
        return ProcessStatus.PASSED

class SetupTestStationStep(ProcessStep):
    @syncRunSingle
    def run(self, ):
        global fh
        
        logger = logging.getLogger(LOGGER_NAME)
        logger.setLevel(logging.DEBUG)
        self.log(LOGGER_NAME)
        self.log(logging.DEBUG)

        msg = "SetupTestStationStep:"
        log_logfile_debugoutput(self, msg)

        #
        # Create file handler
        #
        # Build Chabot log file name:
        # PPCUFR151500001_2015-03-19_15-01-30_TestLog
        #
        timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")

        try:
            serial_number = self.variables["serial_number"]
        except:
            serial_number = ""

        log_file_name = "%s_%s_TestLog.log" % (serial_number,timestamp)
        if not os.path.exists(LOG_FILE_DIR):
            os.makedirs(LOG_FILE_DIR)

        log_file_name = os.path.join(LOG_FILE_DIR, log_file_name)
        fh = logging.FileHandler(log_file_name)
        fh.setLevel(logging.DEBUG)

        # create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s : %(name)s : %(levelname)s : %(message)s')
        fh.setFormatter(formatter)

        # add the handlers to the logger
        logger.addHandler(fh)

        logger.info("*#" * 40)
        logger.info(STATION_NAME+":" + VERSION)
        logger.info("Sequence:EEPROM")
        logger.info("Serial Number:%s" % serial_number)
        logger.info("Timestamp:%s" % timestamp)
        logger.info("*-" * 40)

        startedStations = getRunningStations(self)

        for station in startedStations:

            # Save logger_name
            station.station_execution_context["logger_name"] = LOGGER_NAME
            station.station_execution_context["log_file_name"] = log_file_name

        self.set_pass()
        return ProcessStatus.PASSED

class Get_SN_PN(ProcessStep):
    """Gets the serial number and part number for each station"""

    def __init__(self, processPlan, name="New Process Step", description="", expectedBoardType=None):
        super(Get_SN_PN, self).__init__(processPlan,name=name,description=description)
        self.expectedBoardType = expectedBoardType
        self.syncTimeout = 100000

    @syncRunSingle
    def run(self,):

        try:

            self._config = ConfigParser.RawConfigParser()
            configName = "AllowedParts.cfg"
            self._config.read(os.path.join(os.path.dirname(os.path.realpath(__file__)),  configName))
                       
            allowedHalePartNumbers = self._config.get( "Hale",'AssemblyPartNumbers') 

            self.set_operator_instructions("Scan Serial Number")
            self.log("Scan Serial Number")

            for station in getRunningStations(self):

                prompt = "Scan Board Part Number for UUT %d" % (station.station_id)

                while True:

                    while True:

                        part_num = InputDialog.GetOperatorInput("PN UUT %d" % (station.station_id),prompt)
                        if part_num:
                            part_num = part_num.strip().upper()                    

                        m = PN_PATTERN.match(part_num)
                        if m and m.group() == part_num and part_num[:8] in EEPROM_FRU.NameByPartNumber:
                            print part_num
                            boardType = EEPROM_FRU.NameByPartNumber[part_num[:8]]
                            if not self.expectedBoardType is None and not self.expectedBoardType == boardType:
                                prompt = "Wrong Board Type. Please Scan UUT %d Board PN Again" % (station.station_id)
                            else:
                                station._current_process_plan.variables["board_type"] = boardType
                                station._current_process_plan.variables["board_part_number"] = part_num
                                
                                break
                        else:
                            prompt = "Invalid Part Number. Please Scan UUT %d Board PN Again" % (station.station_id)

                    prompt = "Scan Board Serial Number for UUT %d" % (station.station_id)

                    while True:

                        serial_num = InputDialog.GetOperatorInput("Board SN UUT %d" % (station.station_id),prompt)

                        if serial_num:
                            serial_num = serial_num.strip().upper()

                        m = re.compile(EEPROM_FRU.SN_PatternByName[boardType]).match(serial_num)
                        if m and m.group() == serial_num:
                            print serial_num
                            
                            # ------------                            add 3-Apr-2020 -------------#
                            # get PCBA SN
                            print ">>> from processplan.py"
                            pcbaSN = serial_num
                            print ">>> pcba sn is:", pcbaSN
                            # -------------- Chaitud add 3-Apr-2020 -------------#

                            station._current_process_plan.variables["board_serial_number"] = serial_num
                            
                            break
                        else:
                            prompt = "Invalid Serial Number. Please Scan UUT %d Board SN Again" % (station.station_id)

                    boardDetail = ""

                    #These board types have associated assemblies
                    if boardType in ["Chabot","Hale","Griffith","Fenton","Kepler"]:

                        prompt = "Scan Assembly Part Number for UUT %d" % (station.station_id)

                        while True:

                            part_num = InputDialog.GetOperatorInput("Assembly PN UUT %d" % (station.station_id),prompt)
                            if part_num:
                                part_num = part_num.strip().upper()

                            m = ASSEMBLY_PN_PATTERN.match(part_num)
                            if part_num == station._current_process_plan.variables["board_part_number"]:
                                prompt = "Duplicate PN! Please Scan UUT %d Assembly PN Again" % (station.station_id)
                            elif boardType.startswith("Hale") and not part_num[0:10] in allowedHalePartNumbers:
                                prompt = "Invalid/disallowed Hale PN! Please Scan Assembly PN Again"
                            elif m and m.group() == part_num:
                                print part_num
                           
                                station._current_process_plan.variables["assembly_part_number"] = part_num
                                station._current_process_plan.variables["part_number"] = part_num # we are using assembly PN as the main PN
                                station._current_process_plan.result.partNumber = part_num
                                break
                            else:
                                prompt = "Invalid Part Number. Please Scan UUT %d Assembly PN Again" % (station.station_id)

                        prompt = "Scan Assembly Serial Number for UUT %d" % (station.station_id)

                        isDuplicateSN = False

                        while True:

                            serial_num = InputDialog.GetOperatorInput("SN UUT %d" % (station.station_id),prompt)

                            if serial_num:
                                serial_num = serial_num.strip().upper()

                            m = re.compile(EEPROM_FRU.Assembly_SN_PatternByName[boardType]).match(serial_num)
                            if serial_num == station._current_process_plan.variables["board_serial_number"]:
                                prompt = "Duplicate SN! Please Scan UUT %d Board PN Again" % (station.station_id)
                                isDuplicateSN = True
                                break
                            elif m and m.group() == serial_num:
                                print serial_num
                            
                                # -------------- Chaitud add 7-Apr-2020 -------------#
                                # Check current station after scan TLA SN. Not allow to test if station is not eeprom
                                TlaLabelSN = serial_num
                                status, msg = ck_stn.checkStation(TlaLabelSN)
                                if not status:    
                                    self.set_fail("checkStation", msg )
                                    return ProcessStatus.ABORTED 

                                # Check pcba vs tla are correct or not
                                status, msg = ck_stn.checkTlaSn(pcbaSN,TlaLabelSN)
                                if not status:   
                                    self.set_fail("getTlaSn", msg ) 
                                    return ProcessStatus.ABORTED
                                # -------------- Chaitud add 7-Apr-2020 -------------#
                            
                                station._current_process_plan.variables["assembly_serial_number"] = serial_num
                                station._current_process_plan.variables["serial_number"] = serial_num # we are using assembly SN as the main SN
                                station._current_process_plan.result.serialNumber = serial_num
                                break
                            else:
                                prompt = "Invalid Serial Number. Please Scan UUT %d Assembly SN Again" % (station.station_id)
    
                        if isDuplicateSN:
                            #if the board and assembly SN are the same, start the whole process over - the user may have scanned the assembly SN first
                            continue
                            
                        boardDetail = "%s|%s" % ( station._current_process_plan.variables["board_part_number"], station._current_process_plan.variables["board_serial_number"] )

                    #This board type has associated MAC Address
                    if boardType in ["Kepler"]:

                        prompt = "Scan MAC Adress Label"

                        while True:

                            MAC_addr = InputDialog.GetOperatorInput("Scan MAC Adress Label" ,prompt)
                            if MAC_addr:
                                MAC_addr = MAC_addr.strip().upper()

                            m = MAC_PATTERN.match(MAC_addr)
                            if m and m.group() == MAC_addr:
                                print MAC_addr
                                station._current_process_plan.variables["mac_address"] = MAC_addr
                                break
                            else:
                                prompt = "Invalid MAC Address Number. Please Scan Address Label Again."
                
                        try:
                
                            addr1 = MAC_addr.replace(":","").upper()
                            addr2 = "%012X" % (int(addr1,16)+1)
                    
                            boardDetail = "mac:%s|%s Kepler:" + boardDetail
                        except:
                            pass
                            
                    #if we got here, all SN/PN were okay
                    break
                    
                #Add board PN/SN to 'fail_contdition_0' field which is used for board info in 'forCM' reports
                self.set_reporter_variable('fail_condition_0', boardDetail)

            self.set_pass()
            return ProcessStatus.PASSED
        except Exception, ex:
            self.set_fail("Get_SN_PN", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED

class Program_FRU_EEPROM(ProcessStep):
    """This class implements FRU EEPROM programming"""

    def __init__(self, processPlan, name="New Process Step", description="", programAllFields=False):
        super(Program_FRU_EEPROM, self).__init__(processPlan,name=name,description=description)
        self.programAllFields = programAllFields

    @syncRunSerialized
    def run(self, ):

        try:

            self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

            if self.variables["board_type"] in ["Chabot", "Kepler"]:
                boardName = self.variables["board_type"]
            else:
                boardName = self.variables["board_type"] + str(self.station_id)

            dev,mux = EEPROM_FRU.DevMuxByName[boardName]

            eeprom_contents = {}

            if self.programAllFields:
                if self.variables["board_type"] in ["Chabot","Fenton","Griffith","Hale","Kepler"]:
                    dateOfManufacture = "0x%02x%02x" % (int(self.variables["assembly_serial_number"][6:8]), int(self.variables["assembly_serial_number"][8:10]))
                else:
                    dateOfManufacture = "0x%02x%02x" % (int(self.variables["board_serial_number"][6:8]), int(self.variables["board_serial_number"][8:10]))
                eeprom_contents = EEPROM_FRU._ReadMfgEEPROM(self.global_driver.DUT, dev, mux)
                eeprom_contents["Product Name"] = "PM"
                eeprom_contents["Board Part Number"] = self.variables["board_part_number"]
                eeprom_contents["Board Serial Number"] = self.variables["board_serial_number"]
                eeprom_contents["Card Type"] = EEPROM_FRU.CardTypeByName[self.variables["board_type"]]
                eeprom_contents["Date of Manufacture"] = dateOfManufacture
                eeprom_contents["Hardware Revision"] = "0x" + HARDWARE_REVISION

            if self.variables["board_type"] in ["Chabot","Fenton","Griffith","Hale","Kepler"]:
                eeprom_contents["Module Part Number"] = self.variables["assembly_part_number"]
                eeprom_contents["Module Serial Number"] = self.variables["assembly_serial_number"]

            if self.variables["board_type"] == "Kepler":
                eeprom_contents["MAC Address"] = self.variables["mac_address"]
                eeprom_contents["Number of MAC Addresses"] = "2"

            if self.variables["board_type"] == "Hale":
                eeprom_contents["Low Voltage Margin Table"] = HALE_LOW_VOLTAGE_MARGIN
                eeprom_contents["High Voltage Margin Table"] = HALE_HIGH_VOLTAGE_MARGIN
                eeprom_contents["Nominal Voltage Margin Table"] = HALE_NOMINAL_VOLTAGE_MARGIN

            writeContents = EEPROM_FRU.Uboot_WriteMfgEEPROM(self.global_driver.DUT, dev, mux, eeprom_contents )

            self.set_pass()
            return ProcessStatus.PASSED
        except Exception, ex:
            self.set_fail("Program_FRU_EEPROM", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED

class Verify_FRU_EEPROM(ProcessStep):
    """This class verifies that FRU_EEPROM content is correct"""

    def __init__(self, processPlan, name="New Process Step", description=""):
        super(Verify_FRU_EEPROM, self).__init__(processPlan,name=name,description=description)


    @syncRunSerialized
    def run(self, ):

        try:

            self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

            if self.variables["board_type"] in ["Chabot", "Kepler"]:
                boardName = self.variables["board_type"]
            else:
                boardName = self.variables["board_type"] + str(self.station_id)

            dev,mux = EEPROM_FRU.DevMuxByName[boardName]

            eeprom_contents = EEPROM_FRU._ReadMfgEEPROM(self.global_driver.DUT, dev, mux)

            if self.variables["board_type"] in ["Cameron","Lowell"]:
                dateOfManufacture = "%02x%02x" % (int(self.variables["board_serial_number"][6:8]), int(self.variables["board_serial_number"][8:10]))
            else:
                dateOfManufacture = "%02x%02x" % (int(self.variables["assembly_serial_number"][6:8]), int(self.variables["assembly_serial_number"][8:10]))

            mismatch = False

            if not addParametricResult(self,"Product Name", eeprom_contents["Product Name"] ,"","PM","PM"):
                mismatch = True
            if not addParametricResult(self,"Board PN", eeprom_contents["Board Part Number"] ,"",self.variables["board_part_number"],self.variables["board_part_number"]):
                mismatch = True
            if not addParametricResult(self,"Board SN", eeprom_contents["Board Serial Number"] ,"",self.variables["board_serial_number"],self.variables["board_serial_number"]):
                mismatch = True

            expectedCardType = ("%02x" % int(EEPROM_FRU.CardTypeByName[self.variables["board_type"]],16)).zfill(8)

            if not addParametricResult(self,"Card Type", eeprom_contents["Card Type"] ,"",expectedCardType,expectedCardType):
                mismatch = True
            if not addParametricResult(self,"Date of Manufacture", eeprom_contents["Date of Manufacture"] ,"",dateOfManufacture,dateOfManufacture):
                mismatch = True
            if not addParametricResult(self,"Hardware Revision", eeprom_contents["Hardware Revision"] ,"",HARDWARE_REVISION,HARDWARE_REVISION):
                mismatch = True

            if self.variables["board_type"] in ["Chabot","Fenton","Griffith","Hale"]:
                if not addParametricResult(self,"Assembly Part Number", eeprom_contents["Module Part Number"] ,"",self.variables["assembly_part_number"],self.variables["assembly_part_number"]):
                    mismatch = True
                if not addParametricResult(self,"Assembly Serial Number", eeprom_contents["Module Serial Number"] ,"",self.variables["assembly_serial_number"],self.variables["assembly_serial_number"]):
                    mismatch = True

            if self.variables["board_type"] == "Kepler":
                MAC_Addr = self.variables["mac_address"].replace(":","").upper()
                if not addParametricResult(self,"MAC Address", eeprom_contents["MAC Address"].upper() ,"",MAC_Addr,MAC_Addr):
                    mismatch = True
                if not addParametricResult(self,"Number of MAC Addresses", eeprom_contents["Number of MAC Addresses"] ,"","2".zfill(4),"2".zfill(4)):
                    mismatch = True

            if self.variables["board_type"] == "Hale":
                if not addParametricResult(self,"Low Voltage Margin Table", eeprom_contents["Low Voltage Margin Table"] ,"",HALE_LOW_VOLTAGE_MARGIN,HALE_LOW_VOLTAGE_MARGIN):
                    mismatch = True
                if not addParametricResult(self,"High Voltage Margin Table", eeprom_contents["High Voltage Margin Table"] ,"",HALE_HIGH_VOLTAGE_MARGIN,HALE_HIGH_VOLTAGE_MARGIN):
                    mismatch = True
                if not addParametricResult(self,"Nominal Voltage Margin Table", eeprom_contents["Nominal Voltage Margin Table"] ,"",HALE_NOMINAL_VOLTAGE_MARGIN,HALE_NOMINAL_VOLTAGE_MARGIN):
                    mismatch = True

            if mismatch:
                self.set_fail("Verify_FRU_EEPROM", "One or more EEPROM fields did not match expected values")
                return ProcessStatus.FAILED

            self.set_pass()
            return ProcessStatus.PASSED

        except Exception, ex:
            self.set_fail("Program_FRU_EEPROM", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED

class Initialize_Report_Variables(ProcessStep):
    """This class initializes the variables required for the Data Warehouse Report Writer"""

    def run(self, ):
        self.set_operator_instructions("Initializing DW Reporter Variables")
        self.log("Initializing Reporter Variables")

        self.set_reporter_variable('test_step', PROCESS_STEP)
        self.set_reporter_variable('test_version', VERSION)
        self.set_reporter_variable('software_version', VERSION)
        self.set_reporter_variable('site', self.variables["serial_number"][3:6])
        self.set_reporter_variable('product_type', self.variables["serial_number"][0:3])
        self.set_reporter_variable('test_application', STATION_NAME )

        #todo: what is fail_condition_0?  only CPU has mac_address (two of them) - self.set_reporter_variable('fail_condition_0', "mac:%s" % self.variables['mac_address'])
        self.set_pass()
        return ProcessStatus.PASSED
        
class InitializeOpenTestCloudReportVariables(ProcessStep):
   """Sets up the variables required for dropping data to OpenTest Cloud."""
   def run(self):
       # The platform_name variable is used to set the 'Product Family'
       # for a test record.  A tester in OpenTest cloud must be configured
       # to be allowed to send data for a specific product family.
       self.set_reporter_variable('platform_name', 'palomar-pcba')
       # The 'site' variable must match the 'Factory' of the test system
       # as configured in the OpenTest cloud database.
       
       self._config = ConfigParser.RawConfigParser()
       self._config.read(os.path.join(os.path.dirname(os.path.realpath(__file__)),  'testexec.cfg'))
       
       self.set_reporter_variable('site',  self._config.get('OpenTestCloudReporter','Site'))
       # The 'manufacturer' is recorded to OpenTest cloud
       self.set_reporter_variable('manufacturer', self._config.get('OpenTestCloudReporter','Manufacturer'))
       # The 'assembly gpn' is recorded to OpenTest cloud as the product
       # name.
       self.set_reporter_variable('assembly_gpn', self.variables["assembly_part_number"])
       # The 'test_step' is recorded to OpenTest cloud as the test step name.
       self.set_reporter_variable('test_step', PROCESS_STEP)
       # All other data recorded to OpenTest cloud is gathered from the
       # standard process plan results structure.
       self.set_reporter_variable('build_type', 'PROD')
       self.set_pass()
       return ProcessStatus.PASSED

class Initialize_Google_QDW_Report_Variables(ProcessStep):
    """This example Process Step Shows the variables that need to be initialized in order to drop test records
    directly from Open Test into the Google QDW.  This information is dropped with the entire test result to the
    MongoDB database, and then a special script runs that extracts the key fields to send to the QDW"""

    def run(self):
        #These Variables are all Mandatory and Must Be Supplied for Valid QDW Records
        #
        # MANDATORY
        #
        self.set_reporter_variable('manufacturer', 'Google')
        self.set_reporter_variable('site', 'Google Main Site')
        self.set_reporter_variable('platform_name', 'Mega Platform')
        self.set_reporter_variable('business_group', 'Mega Business')
        self.set_reporter_variable('assembly_part_type', 'Flux Capacitor')
        self.set_reporter_variable('assembly_gpn', 'GPN12345678')
        self.set_reporter_variable('assembly_mpn', 'MPN12345678')
        self.set_reporter_variable('build_type', 'PROD')
        self.set_reporter_variable('build_id', 'MegaBuild')
        self.set_reporter_variable('process_step_name', 'MISSING')

        # These Variables are all Optional and Can be Set anywhere in the script if you want to record them
        #
        # OPTIONAL
        #
        # This variable contains the time to failure in Minutes that can be set prior to failing a test
        self.set_reporter_variable('time_to_failure_min', 60)
        # This variable contains the number of test loops that have occured before a failure
        self.set_reporter_variable('cycle_to_failure', 5)
        # This variable contains the temperature in degrees C at the time of failure
        self.set_reporter_variable('failure_temperature', 25)
        # This variable contains the voltage at the time of failure for voltage margining
        self.set_reporter_variable('failure_voltage', 13.12)
        # This contains the test module name (Not entirely sure what this is....)
        self.set_reporter_variable('test_module_name', 'Test Module 1')
        # This is the test log file name (i.e. the file name you used for a serial log if you made one)
        self.set_reporter_variable('test_log_file_name', 'MyLogFile.txt')
        # This is the SW revision of the UUT
        self.set_reporter_variable('uut_software_revision', '37.8')
        # This si the RMA number
        self.set_reporter_variable('rma_number', '912389283')
        self.set_pass()
        return ProcessStatus.PASSED


class PowerUp(ProcessStep):
                           
    @syncRunSingle
    def run(self, ):
        
        self.station_driver = self.get_station_variable('Driver_System_Station.StationDriver.Driver')
        check_driver_status = self.station_driver.parameters['Station Driver Initialized']
        if not check_driver_status:
            return ProcessStatus.FAILED        
              
        try:
            setPowerRelayState(True)
            timeToDelay = 0-getPowerOnDuration()
            if timeToDelay > 0:
                time.sleep(timeToDelay)  #power-up delay

            self.set_pass()
            return ProcessStatus.PASSED                

        except Exception, ex:
            self.set_fail("PowerUp", traceback.format_exc() )
            return ProcessStatus.FAILED


        
        self.set_pass()
        return ProcessStatus.PASSED    
        
class PowerDown(ProcessStep):
                           
    @syncRunSingle
    def run(self, ):
        
        self.station_driver = self.get_station_variable('Driver_System_Station.StationDriver.Driver')
        check_driver_status = self.station_driver.parameters['Station Driver Initialized']
        if not check_driver_status:
            return ProcessStatus.FAILED        
              
        try:
            setPowerRelayState(False)
            self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
            self.global_driver.DUT.mode = "Unknown"
            time.sleep(5)

            self.set_pass()
            return ProcessStatus.PASSED                

        except Exception, ex:
            self.set_fail("PowerDown", traceback.format_exc() )
            return ProcessStatus.FAILED


        
        self.set_pass()
        return ProcessStatus.PASSED  



class SetMode_PlanetDiags(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):
            
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            self.global_driver.DUT.SetMode("PlanetDiags")
        except Exception, ex:
            self.set_fail("Set Mode PlanetDiags", traceback.format_exc() )
            return ProcessStatus.FAILED
            
        self.set_pass()
        return ProcessStatus.PASSED        
        
class DiagTestStep(ProcessStep):
    "Base class for all diagnostic tests"
    
    def __init__(self, processPlan, name="New Process Step", description="", diagCmd="",timeout=5.0,syncRunSingle=True):
        super(DiagTestStep, self).__init__(processPlan,name=name,description=description)
        self.diagCmd = diagCmd
        self.timeout = timeout
        self.syncRunSingle = syncRunSingle
        
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        try:
            response = self.global_driver.DUT.CommandQuery(self.diagCmd,self.timeout)
            
            if "PASS" in response.upper() and not "FAIL" in response.upper():
                self.set_pass()
                return ProcessStatus.PASSED
            elif "FAIL" in response.upper():
                self.set_fail(self.diagCmd, "Diagnostic command '%s' response indicates failure (see Debug Output for detail)" % self.diagCmd)
                self.log( response )                
                if self.global_driver.DUT.saveFailResponses:                    
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
            else:                            
                self.set_fail(self.diagCmd, "Unexpected response from diagnostic command '%s' (see Debug Output for detail)" % self.diagCmd )
                self.log( response )
                if self.global_driver.DUT.saveFailResponses:
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
        except Exception, ex:              
            self.set_fail(self.diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED
            
class DiagCommandStep(ProcessStep):
    "Base class for all diagnostic commands"
    
    def __init__(self, processPlan, name="New Process Step", description="", diagCmd="",timeout=0.5):
        super(DiagCommandStep, self).__init__(processPlan,name=name,description=description)
        self.diagCmd = diagCmd
        self.timeout = timeout
        self.ignoreErrors = ignoreErrors
        
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        try:
            response = self.global_driver.DUT.CommandQuery(self.diagCmd,self.timeout)
            
            if (not "err" in response.lower() and not 'fail' in response.lower()) or self.ignoreErrors:
                self.set_pass()
                return ProcessStatus.PASSED
            else:                
                self.set_fail(self.diagCmd, "Diagnostic command '%s' response indicates failure (see Debug Output for detail)" % self.diagCmd)
                self.log( response )                
                if self.global_driver.DUT.saveFailResponses:                    
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
        except Exception, ex:              
            self.set_fail(self.diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED
                
class SetMode_LinuxDiags(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            self.global_driver.DUT.SetMode("LinuxDiags")
        except Exception, ex:
            self.set_fail("Set Mode LinuxDiags", traceback.format_exc() )
            return ProcessStatus.FAILED
            
        self.set_pass()
        return ProcessStatus.PASSED
        
class SetMode_Linux(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            self.global_driver.DUT.SetMode("Linux")
        except Exception, ex:
            self.set_fail("Set Mode Linux", traceback.format_exc() )
            return ProcessStatus.FAILED
            
        self.set_pass()
        return ProcessStatus.PASSED

class SetMode_Bootloader(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            self.global_driver.DUT.SetMode("Bootloader")
        except Exception, ex:
            self.set_fail("Set Mode Bootloader", traceback.format_exc() )
            return ProcessStatus.FAILED

        self.set_pass()
        return ProcessStatus.PASSED
                  
class TemperatureTest(ProcessStep):
    "Camera temperature sensor test"
           
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        channel = self.station_id-1

        diagCmd = "temp test %d" % (channel+6)

        try:
            
            response = self.global_driver.DUT.CommandQuery(diagCmd,2)
            
            if "PASS" in response.upper() and not "FAIL" in response.upper():
                self.set_pass()
                return ProcessStatus.PASSED
            elif "FAIL" in response.upper():
                self.set_fail(diagCmd, "Diagnostic command '%s' response indicates failure (see Debug Output for detail)" % diagCmd)
                self.log( response )                
                if self.global_driver.DUT.saveFailResponses:                    
                    self.global_driver.DUT.LogFailResponse(diagCmd,response)
                return ProcessStatus.FAILED
            else:                            
                self.set_fail(diagCmd, "Unexpected response from diagnostic command '%s' (see Debug Output for detail)" % diagCmd )
                self.log( response )
                if self.global_driver.DUT.saveFailResponses:
                    self.global_driver.DUT.LogFailResponse(diagCmd,response)
                return ProcessStatus.FAILED
        except Exception, ex:              
            self.set_fail(diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED

class OperatorInstruction(ProcessStep):
    
    def __init__(self, processPlan, name="New Process Step", description="", dialogTitle="", prompt=""):
        super(OperatorInstruction, self).__init__(processPlan,name=name,description=description)
        self.dialogTitle = dialogTitle
        self.prompt = prompt
    
    @syncRunSingle
    def run(self,):
        InputDialog.InformationDialog(self.dialogTitle, self.prompt) 
        self.set_pass()
        return ProcessStatus.PASSED

class PromptToInsertUUT(ProcessStep):
    def run(self, ):
        """This test demonstrates how to use a multiple option user prompt"""
        self.set_operator_instructions("Insert UUT into Chassis")
        self.log("Operator Input Prompt - Insert UUT into Chassis")
        self.set_operator_input_prompt("Insert UUT into Chassis and click OK",
                                       OperatorInputPromptType.OPTION_LIST, ['OK', 'Cancel'])
        user_input = self.WaitForOperatorInput()
        self.log("User Selected:" + user_input)
        if user_input == "OK":
            self.set_pass()
            return ProcessStatus.PASSED
        else:
            self.set_fail("Prompt to Insert UUT","User Cancel")
            return ProcessStatus.FAILED
        pass

class ReadAmbientConditions(ProcessStep):
    
    _syncLock = threading.Lock()

    def __init__(self, processPlan, name="New Process Step", description=""):
        super(ReadAmbientConditions, self).__init__(processPlan, name=name, description=description)
        self.name = name
        self.threadLock=threading.Lock()

    def run(self,):

        import math

        with ReadAmbientConditions._syncLock:
        
            self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

            self.threadLock.acquire()
            try:                
                temperature = self.global_driver.HumiditySensor.getTemperature()
                humidity = self.global_driver.HumiditySensor.getHumidity() 
                self.add_measurement(Measurement('Ambient Temperature', str(temperature), 'deg C'))
                self.add_measurement(Measurement('Ambient Humidity', str(humidity), 'RH%'))
            except:  
                #ignore any errors
                pass
            finally:
                self.set_pass()
                self.threadLock.release()
                return ProcessStatus.PASSED

class CleanupProcessStep(ProcessStep):
    """This step gets run automatically at the end of any test if it exists
    the pass/fail outcome of the CleanupProcessStep is not evaluated so
    it's not necessary to set a pass/fail status or return a ProcessStatus value"""
    _cleanupLock = threading.RLock()

    def GenerateForCM_JSON(self):
        
        tla_names = { "Chabot":"CPU_MODULE","Hale":"HVD","Griffith":"PSU","Fenton":"FAN","Kepler":"BACK_CHASSIS", "Cameron":"CAMERON2", "Lowell":"LOWELL3" }
        
        board_type = self.variables["board_type"]
                            
        if board_type in ["Chabot","Hale","Griffith","Fenton","Kepler"]:

            boardInfo = {}
            boardInfo["mac_address"] = []
            boardInfo["subla_gpn_name"] = board_type
            boardInfo["subla_gpn"] = self.variables["board_part_number"]
            boardInfo["serial"] = [self.variables["board_serial_number"]]

            forCMDict = {}
            forCMDict["tla_firmware"] = None
            forCMDict["tla_gpn_name"] = tla_names[board_type]
            forCMDict["tla_gpn"] = self.variables["assembly_part_number"]
            forCMDict["tla_sn"] = self.variables["assembly_serial_number"]
            forCMDict["tla_mac_address"] = []
            forCMDict["parts"] =  [boardInfo]

        else:
            forCMDict = {}
            forCMDict["tla_firmware"] = None
            forCMDict["tla_gpn_name"] = tla_names[board_type]
            forCMDict["tla_gpn"] = self.variables["board_part_number"]
            forCMDict["tla_sn"] = self.variables["board_serial_number"]
            forCMDict["tla_mac_address"] = []
            forCMDict["parts"] =  []

        self.set_reporter_variable('fail_condition_0', json.dumps(forCMDict))

    def run(self, ):
        global runningStationCount

        message = "Entering Cleanup Function"
        #print message
        self.log(message)

        try:
            
            try:
                self.GenerateForCM_JSON()
            except:
                pass

            log_file_name = self._process_plan._station_execution_context["log_file_name"]
            serial_number = self.variables["serial_number"]
            station_log_file_name = re.sub("[a-zA-Z0-9]+_", serial_number + "_", log_file_name, 1)
            self.set_reporter_variable('test_log', station_log_file_name )
            
            self.station_driver = self.get_station_variable('Driver_System_Station.StationDriver.Driver')
            
            slotName = self.variables["board_type"]        

            #Append slot number for Fenton/Griffith/Hale since other process plans test these and have slot number suffixes
            if slotName in ["Fenton","Griffith","Hale"]:                  
                slotName += "1"
            
            cycleCount = self.station_driver.IncrementCycleCount( "CycleCount", slotName  )

            self.set_reporter_variable('fail_condition_2', str(cycleCount))  #use fail_condition_2 for test cycle count


            if not log_file_name ==  station_log_file_name:
                sTime = time.time()
                while not os.path.isfile(log_file_name):   # wait until log file is generated
                    time.sleep(1)
                    if time.time()-sTime > 20:
                        break
                else:
                    tmpfilename = station_log_file_name + ".tmp"
                    shutil.copyfile(log_file_name, tmpfilename )
                    with open(tmpfilename,"r") as infile:
                        with open(station_log_file_name,"w") as outfile:
                            #outfile.write( infile.read().replace( "Serial Number:\n", 'Serial Number:%s\n' % serial_number ))
                            outfile.write( re.sub( 'INFO : Serial Number:.*\n', 'INFO : Serial Number:%s\n' % serial_number, infile.read(), 1 ))
                    os.remove(tmpfilename)                          

            try:
                self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
                secondary_log_file_name = os.path.join( self.global_driver.parameters['SecondaryLogPath'], os.path.basename( log_file_name ))
                shutil.copyfile( log_file_name, secondary_log_file_name )
            except:
                pass

        finally:

            with CleanupProcessStep._cleanupLock:

                runningStationCount -= 1

                if runningStationCount == 0:
                    if "board_type" in self.variables and self.variables["board_type"] in ["Hale","Griffith","Fenton"]:
                        #skip power-down because these types are hot-swappable
                        pass
                    else:
                        setPowerRelayState(False)
                        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
                        self.global_driver.DUT.mode = "Unknown"

                    
                    logger = logging.getLogger(LOGGER_NAME)
                    logger.removeHandler(fh)
                    fh.close()
                message = "Exiting Cleanup Function"
                self.log(message)



class MainProcessPlan(ProcessPlan):
    _setupLock = threading.RLock()

    @property
    def version(self):
        """Sets the version of the process plan.
        """
        return VERSION

    @property
    def process_plan_name(self):
        """Sets the process plan name.
        """
        return 'EEPROM'

    def initialize(self):
        global runningStationCount
        with MainProcessPlan._setupLock:
            runningStationCount += 1
        return True

    def execute_cleanup(self, ):
        # print "Entering ExecuteCleanup"
        cleanup = CleanupProcessStep(self, "Cleanup", "Testing the cleanup call")
        cleanup.run()
        print "Exiting ExecuteCleanup"
        pass

    def CreateProcessPlan(self, ):
        print "Created Test Plan"
        run_interactive_tests = False
        myPlan = []
        # Basic Process Step              

        myPlan.append( GetEmployeeNumber(self, 'Get Employee Number', 'Get Employee Number'))        

        myPlan.append( ReportProcessStep(self,'Report Process Step', 'Report Process Step'))

        myPlan.append( Get_SN_PN(self,'Get SN and PN', 'Gets serial and part number'))

        myPlan.append( SetupTestStationStep(self,'Setup', 'Configures logging'))
        
        myPlan.append( Initialize_Report_Variables(self, 'Initialize Report Variables', 'Configures Default Report Variables') )
        myPlan.append(InitializeOpenTestCloudReportVariables(self, 'Initialize OT Cloud Report Variables', 'Configures Default Cloud Report Variables'))

        myPlan.append( PromptToInsertUUT(self,'Prompt to Insert UUT','Prompt to Insert UUT'))

        myPlan.append(ReadAmbientConditions(self, 'Read Ambient Temp/Humidity', 'Read Ambient Temp/Humidity'))

        myPlan.append( PowerUp(self,'PowerUp','Apply Power'))        

        myPlan.append(SetMode_Bootloader(self,'Set Mode Bootloader', 'Set Mode Bootloader'))

        myPlan.append( Program_FRU_EEPROM(self, 'Program FRU EEPROM', 'Programs the EEPROM with FRU data', programAllFields=True) )

        myPlan.append( Verify_FRU_EEPROM(self, 'Verify FRU EEPROM', 'Verifies FRU data from EEPROM ') )
        
        myPlan.append( PowerDown(self,'PowerDown','Remove Power')) 
        
        myPlan.append( PowerUp(self,'PowerUp','Apply Power')) 
        
        myPlan.append(SetMode_Bootloader(self,'Set Mode Bootloader', 'Set Mode Bootloader'))
        
        myPlan.append( Verify_FRU_EEPROM(self, 'Verify FRU EEPROM after power cycle', 'Verifies FRU data from EEPROM after power cycle') )

        return myPlan

def main():
    print "Building Process Plan"
    ec = []
    Plan = MainProcessPlan(ec)
    Plan.CreateProcessPlan()


if __name__ == "__main__":
    main()
