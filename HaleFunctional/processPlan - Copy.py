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
import UpdateDUT
import json
import ConfigParser
from configobj import ConfigObj
from cth_process_steps.check_current_station_step import \
    CheckCurrentStationStep
from cth_process_steps.update_report_variables_step import \
    UpdateReportVariablesStep

PROCESS_STEP = 'FCT'
PRODUCT_NAME = 'Hale'
PRODUCT_FAMILY = 'Palomar'
LOGGER_NAME = 'Palomar'
STATION_NAME = 'HaleFunctional-' + PROCESS_STEP
LOG_FILE_DIR = 'C:/'+STATION_NAME+'-LOG'
VERSION = '0.13'
DISABLED_STATION_PREFIX = "!!!-DISABLED-!!!  "

HARDWARE_REVISION = "0a"
SN_PATTERN = re.compile(r"^PHH[A-Z]{3}\d{9}$")
#PN_PATTERN = re.compile(r"^\d{8}-\d{2}$")
PN_PATTERN = re.compile(r"^\d{10}[0-9A-F]{2}")
ASSEMBLY_PN_PATTERN = re.compile(r"^\d{10}[0-9A-F]{2}")
#PN_PATTERN = re.compile(r"^[0-9\-]{11}$")

#Restrict test to new Hales
EXPECTED_HALE_PN = ""

MAC_PATTERN = re.compile(r"^[0-9A-F]{12}$", re.I)

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


class AbortDisabledStations(ProcessStep):
    
    @syncronize
    def run(self,):

        if "DISABLED" in self._process_plan._global_execution_context['process_stations'][self.station_id]._station_name.upper():
            self._process_plan._global_execution_context['process_stations'][self.station_id]._enabled_reporters = []
            self.end_process_execution()
            self._process_plan._global_execution_context['process_stations'][self.station_id]._status = ProcessStationStatus.IDLE
            self.set_pass()
            return ProcessStatus.ABORTED
        self.set_pass()
        return ProcessStatus.PASSED


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

class GetEmployeeNumber(ProcessStep):
    @syncRunSingle
    def run(self,):                          
        config_name = "en_authorize.cfg"
        prompt = "Enter Employee Number"
        message=prompt        
        while True:           
            
            try:                
                self._config = ConfigParser.RawConfigParser()            
                if not self._config.read(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", config_name)):
                    self.set_fail("Failed to open/parse '%s'" % config_name, "Failed to open/parse '%s'" % config_name)
                    return ProcessStatus.FAILED                    
            except Exception, ex:
                self.set_fail("Failed to open/parse '%s'" % config_name, traceback.format_exc())
                return ProcessStatus.FAILED            
            
            employeeNumber = InputDialog.GetOperatorInput("Employee Number",prompt).strip()
            
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
        

class ReportProcessStep(ProcessStep):
    def run(self,):

        self.add_measurement(Measurement("Process Step", STATION_NAME,"", False, False, "", "",ProcessStatus.PASSED))

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

class ReportChassisConfig(ProcessStep):
    "Reports serial numbers for all modules"
    
    def __init__(self, processPlan, name="New Process Step", description="",timeout=10,ignoreErrors=False):
        super(ReportChassisConfig, self).__init__(processPlan,name=name,description=description)
        self.diagCmd = "info eeprom"
        self.timeout = timeout
        self.ignoreErrors = ignoreErrors

    def parseSubModuleData(self, content):

        startSeachString = 'MANUFACTURING EEPROM INFO'

        i = content.index(startSeachString)

        submodules = {}
        submoduleNames = []

        if i > 0:
            content = content[i+len(startSeachString):]
            i = content.index('===============================================================================')
            content = content[:i]
            for line in content.split('\n'):
                if not line.strip():
                    continue
                tokens = line.split()
                if len(tokens) == 0:
                    continue
                elif len(tokens) == 1:
                    submodule = {}
                    submodules[tokens[0]] = submodule
                    submoduleNames.append(tokens[0])
                else:
                    submodule[tokens[0]] = tokens[1]

        return submodules

    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        try:
            response = self.global_driver.DUT.CommandQuery(self.diagCmd,self.timeout)
            
            try:
                submoduleData = self.parseSubModuleData(response)

                goldenmodules = ["chabot","kepler", "griffith1", "griffith2", "fenton1", "fenton2", "fenton3", "fenton4", 
                        "lowellA","lowellB","cameronA","cameronB"]

                uuts = ["hale1", "hale2", "hale3", "hale4", "hale5", "hale6", "hale7", "hale8", "hale9", "hale10", "hale11", "hale12"]
                                            
                for submodule in uuts:                                    
                    try:                            
                        self.add_measurement(Measurement(submodule + " SN",  submoduleData[submodule]["BOARD_SERIAL_NUMBER"], "", False, False, "", "",ProcessStatus.PASSED))                        
                    except:
                        pass                    
                        
                for goldenmodule in goldenmodules:
                    try:
                        self.add_measurement(Measurement(goldenmodule + " SN (Golden)",  submoduleData[goldenmodule]["BOARD_SERIAL_NUMBER"], "", False, False, "", "",ProcessStatus.PASSED))                        
                    except:
                        pass
                        
            except Exception, ex:
                print ex
                traceback.print_exc()
                pass
            
        except Exception, ex:              
            self.set_fail(self.diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED

        self.set_pass()
        return ProcessStatus.PASSED


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

class Read_FRU_SN_PN(ProcessStep):
     """Gets the serial number and part number for each station"""

     @syncRunSerialized
     def run(self,):
        try:
             self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

            #temp serial number in case we cannot read from FRU
             self.variables["serial_number"] = "station%d" % self.station_id

             dev, mux = EEPROM_FRU.DevMuxByName["Hale%d" % self.station_id]

             eeprom_data = EEPROM_FRU._ReadMfgEEPROM(self.global_driver.DUT,dev,mux)

             if not "Board Serial Number" in eeprom_data:
                self.set_fail("Read_FRU_SN_PN", "No board serial number field in FRU EEPROM")
                return ProcessStatus.FAILED

             serial_num = eeprom_data["Board Serial Number"]

             if serial_num:
                 serial_num = serial_num.strip().upper()
             else:
                 self.set_fail("Read_FRU_SN_PN", "No board serial number")
                 return ProcessStatus.FAILED

             self.variables["board_serial_number"] = serial_num

             m = SN_PATTERN.match(serial_num)
             if m and m.group() == serial_num:
                 print serial_num
                 self.variables["board_serial_number"] = serial_num
             else:
                self.set_fail("Read_FRU_SN_PN", "Invalid board serial number: %s" % serial_num)
                return ProcessStatus.FAILED

             if not "Board Part Number" in eeprom_data:
                self.set_fail("Read_FRU_SN_PN", "No board part number field in FRU EEPROM")
                return ProcessStatus.FAILED

             part_num = eeprom_data["Board Part Number"]

             if part_num:
                 part_num = part_num.strip().upper()
             else:
                 self.set_fail("Read_FRU_SN_PN", "No board part number")
                 return ProcessStatus.FAILED

             self.variables["board_part_number"] = part_num

             m = PN_PATTERN.match(part_num)
             if m and m.group() == part_num:
                 print part_num
                 self.variables["board_part_number"] = part_num
             else:
                self.set_fail("Read_FRU_SN_PN", "Invalid board part number: %s" % part_num)
                return ProcessStatus.FAILED

            #==================================================
            # Assembly
            #==================================================
            
             if not "Module Serial Number" in eeprom_data:
                self.set_fail("Read_FRU_SN_PN", "No module serial number field in FRU EEPROM")
                return ProcessStatus.FAILED

             serial_num = eeprom_data["Module Serial Number"]

             if serial_num:
                 serial_num = serial_num.strip().upper()
             else:
                 self.set_fail("Read_FRU_SN_PN", "No module serial number")
                 return ProcessStatus.FAILED

             self.variables["assembly_serial_number"] = serial_num

             m = SN_PATTERN.match(serial_num)
             if m and m.group() == serial_num:
                 print serial_num
                 self.variables["assembly_serial_number"] = serial_num
                 self.variables["serial_number"] = serial_num
                 self._process_plan.result.serialNumber = serial_num
             else:
                self.set_fail("Read_FRU_SN_PN", "Invalid module serial number: %s" % serial_num)
                return ProcessStatus.FAILED

             if not "Module Part Number" in eeprom_data:
                self.set_fail("Read_FRU_SN_PN", "No module part number field in FRU EEPROM")
                return ProcessStatus.FAILED

             part_num = eeprom_data["Module Part Number"]

             if part_num:
                 part_num = part_num.strip().upper()
             else:
                 self.set_fail("Read_FRU_SN_PN", "No board part number")
                 return ProcessStatus.FAILED

             #if part_num[0:10] != EXPECTED_HALE_PN:
             #    self.SetFail("Read_FRU_SN_PN", "Invalid part number: %s, expected: %s" % (part_num, EXPECTED_HALE_PN))
             #    return ProcessStatus.FAILED

             self.variables["assembly_part_number"] = part_num

             m = PN_PATTERN.match(part_num)
             if m and m.group() == part_num:
                 print part_num
                 self.variables["assembly_part_number"] = part_num
                 self.variables["part_number"] = part_num
                 self.set_part_number(part_num)
             else:
                self.set_fail("Read_FRU_SN_PN", "Invalid module part number: %s" % part_num)
                return ProcessStatus.FAILED

             #Add board PN/SN to 'fail_contdition_0' field which is used for board info in 'forCM' reports
             self.set_reporter_variable('fail_condition_0', "%s|%s" % ( self.variables["board_part_number"], self.variables["board_serial_number"] ))

             self.set_pass()
             return ProcessStatus.PASSED

        except Exception, ex:
                self.set_fail("Read_FRU_SN_PN", repr(traceback.format_exc()) )
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
       self.set_reporter_variable('product_name', 'Hale')
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


class PromptForInputTest(ProcessStep):
    def __init__(self, processPlan, name="New Process Step", description="", prompt="",timeout=60):
        super(PromptForInputTest, self).__init__(processPlan,name=name,description=description)
        self.prompt = prompt
        self.timeout = timeout

    @syncRunSingle
    def run(self, ):
        self.set_operator_instructions(self.prompt)
        self.set_operator_input_prompt(self.prompt, OperatorInputPromptType.OPTION_LIST, ['OK',])
        user_input = self.WaitForOperatorInput()
        while user_input != "OK":
                user_input = self.WaitForOperatorInput()
        self.set_operator_instructions("")
        self.set_pass()
        return ProcessStatus.PASSED

class PromptTest(ProcessStep):
    """This Function Prompts The User For Input using a pop-up window"""

    @syncRunSingle
    def run(self, ):
        self.set_operator_instructions("Testing Operator Input Prompt")
        self.log("Testing Operator Input Prompt")
        self.set_operator_input_prompt("Please Enter Some Information to continue...", OperatorInputPromptType.FREEFORM,
            [])
        self.WaitForOperatorInput()
        self.set_pass()
        return ProcessStatus.PASSED
        pass


class DisplayPromptTest(ProcessStep):
    def __init__(self, processPlan, name="New Process Step", description="", displayID=""):
        super(DisplayPromptTest, self).__init__(processPlan,name=name,description=description)
        self.displayID = displayID

    @syncRunSingle
    def run(self, ):
        """Prompts operator to verify display output"""
        user_input = ""

        while not user_input in ["PASS","FAIL"]:
            self.set_operator_input_prompt("Verify image on display %s" % self.displayID,
                                           OperatorInputPromptType.OPTION_LIST, ['PASS', 'FAIL'])
            user_input = self.WaitForOperatorInput()
            self.log("Operator Selected:" + user_input)
        if user_input == "PASS":
            self.set_pass()
            return ProcessStatus.PASSED
        else:
            self.set_fail( "Verify image on display %s" % self.displayID, "Operator indicated 'FAIL' for display %s image" % self.displayID)
            return ProcessStatus.FAILED

class QueryUpdateHaleFirmware(ProcessStep):

    def run(self, ):
            
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        QueryUpdateHaleFirmware.MD5sums = None

        try:

            #expectedMD5sum = "a6beb945268f2cb02afd2a320c374d2a"                   
            expectedMD5sum = "edd138cd722edafa117e2dc8d44c3f33"
            with SyncObject(self,300.0,True) as shouldRun:        #sync all nests and run test in only one thread
                if shouldRun:                   
                    imageFile = "15000301-05.bin"
                    QueryUpdateHaleFirmware.MD5sums = UpdateDUT.queryHaleMD5sums( self.global_driver.DUT )
                    
                    shouldUpdate = False
                    for MD5sum in QueryUpdateHaleFirmware.MD5sums:
                        if not MD5sum == expectedMD5sum and not MD5sum == "":
                            shouldUpdate = True
                    
                    if shouldUpdate:
                        UpdateDUT.updateAllHales( self.global_driver.DUT, imageFile )
                        QueryUpdateHaleFirmware.MD5sums = UpdateDUT.queryHaleMD5sums( self.global_driver.DUT )                
            
            self.variables["Hale_MD5_Sum"] = QueryUpdateHaleFirmware.MD5sums[self.station_id-1]

            if not addParametricResult( self, "Hale MD5 sum", QueryUpdateHaleFirmware.MD5sums[self.station_id-1], "", expectedMD5sum, expectedMD5sum ):
                return ProcessStatus.FAILED

            self.set_pass()
            return ProcessStatus.PASSED

                
        except Exception, ex:
            self.set_fail("QueryUpdateHaleFirmware", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED
            
        self.set_pass()
        return ProcessStatus.PASSED

class QueryUpdateDiagFirmware(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):
            
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            expectedRevision = "2.21"
            imageFilename = "imageset-rel2.21.tgz"
            revision = UpdateDUT.queryFirmwareRevision( self.global_driver.DUT )
            if revision != expectedRevision:
                UpdateDUT.updateFirmware( self.global_driver.DUT, imageFilename )
                revision = UpdateDUT.queryFirmwareRevision( self.global_driver.DUT )

            if not addParametricResult( self, "Diag Firmware Revision", revision, "", expectedRevision, expectedRevision ):
                return ProcessStatus.FAILED
        except Exception, ex:
            self.set_fail("QueryUpdateDiagFirmware", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED
            
        self.set_pass()
        return ProcessStatus.PASSED

class QueryUpdateNellieFPGAFirmware(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):

        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            expectedRevision = "00000008"
            imageFilename = "15000312-02.bin"
            status = ProcessStatus.PASSED
            revision = UpdateDUT.queryNellieFPGAVersion( self.global_driver.DUT )
            if revision != expectedRevision:
                if not UpdateDUT.updateFPGA( self.global_driver.DUT, imageFilename, "nellie" ):
                    self.set_fail("UpdateNellieFPGAFirmware", "Nellie FPGA Firmware update failed")
                    status = ProcessStatus.FAILED
                revision = UpdateDUT.queryNellieFPGAVersion( self.global_driver.DUT )

            if not addParametricResult( self, "Nellie FPGA Firmware Revision", revision, "", expectedRevision, expectedRevision ):
                status = ProcessStatus.FAILED
        except Exception, ex:
            self.set_fail("QueryUpdateNellieFPGAFirmware", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED

        if status == ProcessStatus.PASSED:
            self.set_pass()
        return status

class QueryUpdateLeahFPGAFirmware(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):

        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            expectedRevision = "0000020f"
            imageFilename = "15000313-02.bin"
            status = ProcessStatus.PASSED
            revision = UpdateDUT.queryLeahFPGAVersion( self.global_driver.DUT )
            if revision != expectedRevision:
                if not UpdateDUT.updateFPGA( self.global_driver.DUT, imageFilename, "leah" ):
                    self.set_fail("UpdateLeahFPGAFirmware", "Leah FPGA Firmware update failed")
                    status = ProcessStatus.FAILED
                revision = UpdateDUT.queryLeahFPGAVersion( self.global_driver.DUT )

            if not addParametricResult( self, "Leah FPGA Firmware Revision", revision, "", expectedRevision, expectedRevision ):
                status = ProcessStatus.FAILED
        except Exception, ex:
            self.set_fail("QueryUpdateLeahFPGAFirmware", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED

        if status == ProcessStatus.PASSED:
            self.set_pass()
        return status

class QueryUpdateUBoot(ProcessStep):
    ''''''
    @syncRunSingle
    def run(self, ):

        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        try:
            expectedRevision = "7.0.18"
            imageFilename = "15000311-02.bin"
            revision = UpdateDUT.queryUBootRevision( self.global_driver.DUT )
            if revision != expectedRevision:
                UpdateDUT.updateUBoot( self.global_driver.DUT, imageFilename )
                revision = UpdateDUT.queryUBootRevision( self.global_driver.DUT )

            if not addParametricResult( self, "UBoot Revision", revision, "", expectedRevision, expectedRevision ):
                return ProcessStatus.FAILED
        except Exception, ex:
            self.set_fail("QueryUpdateUBoot", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED

        self.set_pass()
        return ProcessStatus.PASSED

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
                if self.variables["board_type"] in ["Chabot","Fenton","Griffith","Hale"]:
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

            if self.variables["board_type"] in ["Chabot","Fenton","Griffith","Hale"]:
                eeprom_contents["Module Part Number"] = self.variables["assembly_part_number"]
                eeprom_contents["Module Serial Number"] = self.variables["assembly_serial_number"]

            if self.variables["board_type"] == "Kepler":
                eeprom_contents["MAC Address"] = self.variables["mac_address"]
                eeprom_contents["Number of MAC Addresses"] = "2"

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
                if not addParametricResult(self,"MAC Address", eeprom_contents["MAC Address"] ,"",self.variables["mac_address"],self.variables["mac_address"]):
                    mismatch = True
                if not addParametricResult(self,"Number of MAC Addresses", eeprom_contents["Number of MAC Addresses"] ,"","2".zfill(4),"2".zfill(4)):
                    mismatch = True

            if mismatch:
                self.set_fail("Verify_FRU_EEPROM", "One or more EEPROM fields did not match expected values")
                return ProcessStatus.FAILED

            self.set_pass()
            return ProcessStatus.PASSED

        except Exception, ex:
            self.set_fail("Program_FRU_EEPROM", repr(traceback.format_exc()) )
            return ProcessStatus.FAILED

class QueryDiagFirmware(ProcessStep):
    '''Queries and reports the diag firmware revision'''    
    @syncRunSerialized
    def run(self,):
            
        self.station_driver = self.get_station_variable('Driver_System_Station.StationDriver.Driver')        
        try:
            revision = UpdateDUT.queryFirmwareRevision( self.station_driver.DUT )
                
            #Add diag firmware revision to 'fail_contdition_0' field which is used for sub-module info in 'forCM' reports
            self.variables["Diag_FW_revision"] = revision
            self.set_reporter_variable('uut_software_version', revision)

            self.add_measurement(Measurement("Diag Firmware Revision", revision, "", False, False, "", "",ProcessStatus.PASSED))

        except Exception, ex:
            pass
            
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
                self.set_fail(self.diagCmd, "Diagnostic command '%s' response indicates failure:\n%s" % (self.diagCmd,response))
                self.log( response )                
                if self.global_driver.DUT.saveFailResponses:                    
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
            else:                            
                self.set_fail(self.diagCmd, "Unexpected response from diagnostic command '%s':\n %s"  % (self.diagCmd,response ))
                self.log( response )
                if self.global_driver.DUT.saveFailResponses:
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
        except Exception, ex:              
            self.set_fail(self.diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED            

class DiagCommandStep(ProcessStep):
    "Base class for all diagnostic commands"
    
    def __init__(self, processPlan, name="New Process Step", description="", diagCmd="",timeout=0.5,ignoreErrors=False,syncRunSingle=True):
        super(DiagCommandStep, self).__init__(processPlan,name=name,description=description)
        self.diagCmd = diagCmd
        self.timeout = timeout
        self.ignoreErrors = ignoreErrors
        self.syncRunSingle = syncRunSingle
        
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

class PowerSeqTest(ProcessStep):
    "Powerseq test"
    
    def __init__(self, processPlan, name="New Process Step", description="",timeout=5.0):
        super(PowerSeqTest, self).__init__(processPlan,name=name,description=description)        
        self.timeout = timeout
        
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        self.diagCmd = "powerseq test %d" % self.station_id

        try:
            response = self.global_driver.DUT.CommandQuery(self.diagCmd,self.timeout)
            
            if "PASS" in response.upper() and not "FAIL" in response.upper():
                self.set_pass()
                return ProcessStatus.PASSED
            elif "FAIL" in response.upper():
                self.set_fail(self.diagCmd, "Diagnostic command '%s' response indicates failure:\n%s" % (self.diagCmd,response))
                self.log( response )                
                if self.global_driver.DUT.saveFailResponses:                    
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
            else:                            
                self.set_fail(self.diagCmd, "Unexpected response from diagnostic command '%s':\n %s"  % (self.diagCmd,response ))
                self.log( response )
                if self.global_driver.DUT.saveFailResponses:
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
        except Exception, ex:              
            self.set_fail(self.diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED

class DiagI2CHale(ProcessStep):
    "Hale I2C Core Test"
    response = None

    def __init__(self, processPlan, name="New Process Step", description="", timeout=5.0):
        super(DiagI2CHale, self).__init__(processPlan,name=name,description=description)
        self.timeout = timeout

    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        DiagI2CHale.response = None

        try:
            with SyncObject(self,self.timeout,True) as shouldRun:        #sync all nests and run test in only one thread
                if shouldRun:
                    DiagI2CHale.response = self.global_driver.DUT.CommandQuery("diag_i2c hale",self.timeout)

            response = DiagI2CHale.response

            mux = self.station_id-1

            if "PASS" in response.upper() and not "FAIL" in response.upper():
                self.set_pass()
                return ProcessStatus.PASSED
            else:
                searchString1 = 'Failed to find'
                searchString2 = 'on bus(6) mux(%d)' % (mux)
                if searchString1 in response and searchString2 in response:
                    self.set_fail("diag_i2c hale", "Unexpected response from diagnostic command 'diag_i2c hale' (see Debug Output for detail)")
                    self.log( response )
                    if self.global_driver.DUT.saveFailResponses:
                        self.global_driver.DUT.LogFailResponse("diag_i2c hale",response)
                    return ProcessStatus.FAILED
                else:
                    searchString = 'ADM1177 HS Ctrlr/Pwr Mon: bus(6)  mux(%d)' % (mux)
                    if searchString in response:
                        self.set_pass()
                        return ProcessStatus.PASSED
                    else:
                        self.set_fail("diag_i2c hale","Unexpected response from diagnostic command 'diag_i2c hale' (see Debug Output for detail)")
                        self.log( response )
        except Exception, ex:
            self.set_fail("diag_i2c hale", traceback.format_exc() )
            return ProcessStatus.FAILED
            
class PromTest(ProcessStep):
    "Prom Test"
    response = None

    def __init__(self, processPlan, name="New Process Step", description="", timeout=5.0):
        super(PromTest, self).__init__(processPlan,name=name,description=description)
        self.timeout = timeout

    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        PromTest.response = None

        try:
            with SyncObject(self,self.timeout,True) as shouldRun:        #sync all nests and run test in only one thread
                if shouldRun:
                    PromTest.response = self.global_driver.DUT.CommandQuery("prom test",self.timeout)

            response = PromTest.response

            if "PASS" in response.upper() and not "FAIL" in response.upper():
                self.set_pass()
                return ProcessStatus.PASSED
            else:
                searchString1 = 'FAIL'
                searchString2 = 'hale%d_' % self.station_id
  
                #if 'FAIL' not found in response then something went wrong with the command/response - we should fail all hales
                if searchString1 in response:
                    if searchString2 in response:
                        self.set_fail("prom test", "Unexpected response from diagnostic command 'prom test'\n %s" % response)
                        self.log( response )
                        if self.global_driver.DUT.saveFailResponses:
                            self.global_driver.DUT.LogFailResponse("prom test",response)
                        return ProcessStatus.FAILED
                    else:                           
                            self.set_pass()
                            return ProcessStatus.PASSED
                else:
                    self.set_fail("prom test","Unexpected response from diagnostic command 'prom test'\n %s" % response)
                    self.log( response )
        except Exception, ex:
            self.set_fail("prom test", traceback.format_exc() )
            return ProcessStatus.FAILED

class HVDriverScreen(ProcessStep):
    "HV Driver Screen Test"
    response = None

    def __init__(self, processPlan, name="New Process Step", description="", timeout=5.0):
        super(HVDriverScreen, self).__init__(processPlan,name=name,description=description)
        self.timeout = timeout

    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        HVDriverScreen.response = None

        try:
            with SyncObject(self,self.timeout,True) as shouldRun:        #sync all nests and run test in only one thread
                if shouldRun:
                    HVDriverScreen.response = self.global_driver.DUT.CommandQuery("hv_driver screen all 5",self.timeout)

            response = HVDriverScreen.response

            haleNum = self.station_id

            if "PASS" in response.upper() and not "FAIL" in response.upper():
                self.set_pass()
                return ProcessStatus.PASSED
            else:
                searchString = 'hale%d_' % haleNum
                searchString2 = 'hale%d ' % haleNum
                if searchString in response or searchString2 in response:
                    self.set_fail("hv_driver screen all", "Unexpected response from diagnostic command 'hv_driver screen all': \n%s" % response)
                    self.log( response )
                    if self.global_driver.DUT.saveFailResponses:
                        self.global_driver.DUT.LogFailResponse("hv_driver screen all",response)
                    return ProcessStatus.FAILED
                else:

                    self.set_pass()
                    return ProcessStatus.PASSED

        except Exception, ex:
            self.set_fail("hv_driver screen all", traceback.format_exc() )
            return ProcessStatus.FAILED
            
class HVDriverOn(ProcessStep):
    "HVDriverOn test"
    
    def __init__(self, processPlan, name="New Process Step", description="",timeout=5.0):
        super(HVDriverOn, self).__init__(processPlan,name=name,description=description)        
        self.timeout = timeout
        
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        self.diagCmd = "hv_driver power %d true" % (self.station_id-1)

        try:
            response = self.global_driver.DUT.CommandQuery(self.diagCmd,self.timeout)
            
            if "FAIL" in response.upper() or 'ERROR' in response.upper():
                self.set_fail(self.diagCmd, "Diagnostic command '%s' response indicates failure:\n%s" % (self.diagCmd,response))
                self.log( response )                
                if self.global_driver.DUT.saveFailResponses:                    
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
            else:                            
                self.set_pass()
                return ProcessStatus.PASSED
        except Exception, ex:              
            self.set_fail(self.diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED            
            
class HVDriverOff(ProcessStep):
    "HVDriverOff test"
    
    def __init__(self, processPlan, name="New Process Step", description="",timeout=5.0):
        super(HVDriverOff, self).__init__(processPlan,name=name,description=description)        
        self.timeout = timeout
        
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        self.diagCmd = "hv_driver power %d false" % (self.station_id-1)

        try:
            response = self.global_driver.DUT.CommandQuery(self.diagCmd,self.timeout)
            
            if "FAIL" in response.upper() or 'ERROR' in response.upper():
                self.set_fail(self.diagCmd, "Diagnostic command '%s' response indicates failure:\n%s" % (self.diagCmd,response))
                self.log( response )                
                if self.global_driver.DUT.saveFailResponses:                    
                    self.global_driver.DUT.LogFailResponse(self.diagCmd,response)
                return ProcessStatus.FAILED
            else:                            
                self.set_pass()
                return ProcessStatus.PASSED
        except Exception, ex:              
            self.set_fail(self.diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED         

class DiagI2CHale_old(ProcessStep):
    "Hale I2C Test"
    response = None

    def __init__(self, processPlan, name="New Process Step", description="", timeout=5.0):
        super(DiagI2CHale, self).__init__(processPlan,name=name,description=description)
        self.timeout = timeout

    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        try:
            self.global_driver.DUT.CommandQuery("i2c dev 6",self.timeout)
            self.global_driver.DUT.CommandQuery("i2c mux %d" % (self.station_id-1),self.timeout)
            response = self.global_driver.DUT.CommandQuery("i2c probe",self.timeout)

            if '00 34 41 4C 4D 4E 4F 50 58' in response or '01 34 41 4C 4D 4E 4F 50 58' in response:
                self.set_pass()
                return ProcessStatus.PASSED
            else:
                self.set_fail("diag_i2c hale", "Unexpected response from diagnostic command 'diag_i2c hale': %s" % response)
                self.log( response )
                if self.global_driver.DUT.saveFailResponses:
                    self.global_driver.DUT.LogFailResponse("diag_i2c hale",response)
                return ProcessStatus.FAILED
        except Exception, ex:
            self.set_fail("diag_i2c hale", traceback.format_exc() )
            return ProcessStatus.FAILED

class DiagIntrHale(ProcessStep):
    "Hale Intr Test"
    response = None

    def __init__(self, processPlan, name="New Process Step", description="", timeout=30.0):
        super(DiagIntrHale, self).__init__(processPlan,name=name,description=description)
        self.timeout = timeout

    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        DiagIntrHale.response = None

        try:
            with SyncObject(self,self.timeout,True) as shouldRun:        #sync all nests and run test in only one thread
                if shouldRun:
                    DiagIntrHale.response = self.global_driver.DUT.CommandQuery("diag_intr ignore present",self.timeout)

            response = DiagIntrHale.response
            
            mux = (self.station_id ) -1

            if "PASS" in response.upper() and not "FAIL" in response.upper():
                self.set_pass()
                return ProcessStatus.PASSED
            else:
                searchString1 = 'testing interrupt 6:%d\r' % (mux)
                searchString2 = 'Missing presence for interrupt 6:%d\r' % (mux)
                if searchString1 in response and not searchString2 in response:
                    self.set_pass()
                    return ProcessStatus.PASSED
                else:
                    self.set_fail("diag_intr ignore present", "Unexpected response from diagnostic command 'diag_intr ignore present' (see Debug Output for detail)" )
                    self.log( response )
                    if self.global_driver.DUT.saveFailResponses:
                        self.global_driver.DUT.LogFailResponse("diag_intr ignore present",response)
                    return ProcessStatus.FAILED

        except Exception, ex:
            self.set_fail("diag_intr ignore present", traceback.format_exc() )
            return ProcessStatus.FAILED

class Diag_I2C_Local(ProcessStep):
    ''''''

    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        if self.global_driver.DUT.ExecuteDiag("diag_i2c local"):
            self.set_pass()
            return ProcessStatus.PASSED
        else:
            self.set_fail()
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

class PowerUp(ProcessStep):
                           
    @syncRunSingle
    def run(self, ):
        
        self.station_driver = self.get_station_variable('Driver_System_Station.StationDriver.Driver')
        check_driver_status = self.station_driver.parameters['Station Driver Initialized']
        if not check_driver_status:
            return ProcessStatus.FAILED        
              
        try:
            setPowerRelayState(True)
            timeToDelay = 0.0-getPowerOnDuration()
            if timeToDelay > 0:
                time.sleep(timeToDelay)  #power-up delay

            self.set_pass()
            return ProcessStatus.PASSED

        except Exception, ex:
            self.set_fail("PowerUp", traceback.format_exc() )
            return ProcessStatus.FAILED

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
        
class Delay(ProcessStep):
    
    def __init__(self, processPlan, name="New Process Step", description="", delay=2.0):
        super(Delay, self).__init__(processPlan,name=name,description=description)
        self.delay = delay
    
    @syncRunSingle
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
        time.sleep(self.delay)
        self.set_pass()
        return ProcessStatus.PASSED


class TemperatureTest(ProcessStep):
    "Hale temperature sensor test"
           
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        channels = []
        for channel in range(self.station_id*8+6,self.station_id*8+14):
            channels.append("%d" % channel)
        channelList = ",".join(channels)

        diagCmd = "temp test %s" % channelList

        try:
            
            response = self.global_driver.DUT.CommandQuery(diagCmd,10)
            
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
            
class TemperatureDump(ProcessStep):
    "Hale temperature sensor dump"
           
    @syncRunSerialized
    def run(self, ):
        self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')

        channels = []
        for channel in range(self.station_id*8+6,self.station_id*8+14):
            channels.append("%d" % channel)
        channelList = ",".join(channels)

        diagCmd = "temp dump %s" % channelList
        try:
            
            response = self.global_driver.DUT.CommandQuery(diagCmd,2)            
            
            for line in response.split('\r'):
                if 'hale' in line:
                    try:
                        sensor_name = line.split()[1]
                        temp = float(line.split()[2])             
                        self.add_measurement(Measurement(sensor_name, temp, "C", is_parametric=False, is_numeric=True))                        
                    except:
                        self.set_fail(diagCmd, traceback.format_exc() )
                        return ProcessStatus.FAILED            
        except:
            self.set_fail(diagCmd, traceback.format_exc() )
            return ProcessStatus.FAILED
                
        self.set_pass()
        return ProcessStatus.PASSED
        
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
        boardInfo = {}
        boardInfo["mac_address"] = []
        boardInfo["subla_gpn_name"] = "Hale"
        boardInfo["subla_gpn"] = self.variables["board_part_number"]
        boardInfo["serial"] = [self.variables["board_serial_number"]]        
                            
        forCMDict = {}
        forCMDict["tla_firmware"] = self.variables["Hale_MD5_Sum"]
        forCMDict["tla_gpn_name"] = "HVD"
        forCMDict["tla_gpn"] = self.variables["assembly_part_number"]
        forCMDict["tla_sn"] = self.variables["assembly_serial_number"]
        forCMDict["tla_mac_address"] = []
        forCMDict["parts"] =  [boardInfo]
        
        self.set_reporter_variable('fail_condition_0', json.dumps(forCMDict))

    def check_for_consecutive_failures(self):                       
        with CleanupProcessStep._configFileLock:
            try:
                station_name = self._process_plan.global_execution_context['process_stations'][self.station_id].station_name                
                
                if not "DISABLED" in station_name.upper():
                    filename = os.path.join(os.path.dirname(os.path.abspath(__file__)),"testexec.cfg")
                    config_parser = MyConfigObj(filename)                    
                    try:
                        try:
                            section = config_parser['ConsecutiveFailCount']
                        except:
                            config_parser['ConsecutiveFailCount'] = {}                        
                                                            
                        if self._process_plan.result.StatusResult == ProcessStatus.FAILED:
                            try:
                                fail_count = int(config_parser['ConsecutiveFailCount'][station_name])
                            except:
                                fail_count = 0

                            fail_count += 1                        

                            config_parser['ConsecutiveFailCount'][station_name] = str(fail_count)
                            
                            if not "ConsecutiveFailHandling" in config_parser:
                                config_parser['ConsecutiveFailHandling'] = {}
                                config_parser['ConsecutiveFailHandling']['consecutive_fail_limit'] = "2"
                           
                            try:
                                consecutive_fail_limit = int(config_parser['ConsecutiveFailHandling']['consecutive_fail_limit'])
                            except:
                                consecutive_fail_limit = 2

                            if fail_count >= consecutive_fail_limit:
                                config_parser['StationNames']['station' + str(self.station_id)] =  DISABLED_STATION_PREFIX + station_name                                             
                              
                        else:
                            config_parser['ConsecutiveFailCount'][station_name] = "0"
                    finally:
                        config_parser.write()
            except Exception, ex:
                try:
                    self.raise_alert("Consecutive failure check failed [%s]" % repr(ex), UIAlertLevel.WARNING)
                except:
                    pass

    def run(self, ):
        global runningStationCount

        message = "Entering Cleanup Function"
        #print message
        self.log(message)

        try:
            
            try:
                self.check_for_consecutive_failures()
            except:
                pass            
            
            try:
                self.GenerateForCM_JSON()
            except:
                pass

            log_file_name = self._process_plan._station_execution_context["log_file_name"]
            serial_number = self.variables["serial_number"]
            station_log_file_name = re.sub("[a-zA-Z0-9]+_", serial_number + "_", log_file_name, 1)
            self.set_reporter_variable('test_log', station_log_file_name )
            
            self.station_driver = self.get_station_variable('Driver_System_Station.StationDriver.Driver')
            cycleCount = self.station_driver.IncrementCycleCount( "CycleCount" % (self.getChassisId()+1), "Hale%d" % self.station_id )

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
                    setPowerRelayState(False)

                    self.global_driver = self.get_global_variable('Driver_System_Station.SharedDriver.Driver')
                    self.global_driver.DUT.mode = "Unknown"
                    logger = logging.getLogger(LOGGER_NAME)
                    logger.removeHandler(fh)
                    fh.close()

                message = "Exiting Cleanup Function"
                self.log(message)


class MyConfigObj(ConfigObj):

    def __init__(self, *args, **kwargs):
        ConfigObj.__init__(self, *args, **kwargs)

    def _unquote(self, value):
         return value

    def _quote(self, value, multiline=True):
        return value


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
        return 'Hale FCT Plan'

    def initialize(self):
        global runningStationCount
        with MainProcessPlan._setupLock:
            runningStationCount += 1

        self.variables['process_step'] = PROCESS_STEP
        self.variables['product_name'] = PRODUCT_NAME
        self.variables['product_family'] = PRODUCT_FAMILY

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

        
        
        #myPlan.append( AbortDisabledStations(self, "Abort Disabled Stations", "Abort Disabled Stations"))       
          
        myPlan.append( GetEmployeeNumber(self, 'Get Employee Number', 'Get Employee Number'))        

        myPlan.append( ReportProcessStep(self,'Report Process Step', 'Report Process Step'))

        myPlan.append(ReadAmbientConditions(self, 'Read Ambient Temp/Humidity', 'Read Ambient Temp/Humidity'))
        #myPlan.append(PromptForInputTest(self,'PowerUp', 'Apply Power', prompt='Please check whether the Hale 12 unit is plugged in well.'))  
        myPlan.append( PowerUp(self,'PowerUp','Apply Power'))

        myPlan.append(SetMode_Bootloader(self,'Set Mode Bootloader', 'Configures DUT for Bootloader'))

        myPlan.append( Read_FRU_SN_PN(self,'Reads SN and PN from FRU EEPROM', 'Reads SN and PN from FRU EEPROM'))

        myPlan.append( SetupTestStationStep(self,'Setup', 'Configures logging'))

        myPlan.append(Initialize_Report_Variables(self, 'Initialize Report Variables', 'Configures Default Report Variables'))
        
        myPlan.append(InitializeOpenTestCloudReportVariables(self, 'Initialize OT Cloud Report Variables', 'Configures Default Cloud Report Variables'))

        # CTH Modules
        myPlan.append(CheckCurrentStationStep(self, 'Check Current Station', 'Check Current Station'))
        myPlan.append(UpdateReportVariablesStep(self, 'Update Report Variables', 'Update Report Variables'))

        myPlan.append(QueryUpdateHaleFirmware(self, 'Query/Update Hale firmware', 'Queries MD5 sum and updates firmware if needed' ))

        myPlan.append(SetMode_PlanetDiags(self,'Set Mode Planet Diags', 'Configures DUT for PlanetDiags'))
        
        myPlan.append(DiagI2CHale(self,'Diag I2C Hale', 'Hale I2C diagnostic test'))
        
        myPlan.append(DiagIntrHale(self,'Diag intr', 'Interruptr diagnostic test'))

        myPlan.append(SetMode_Linux(self,'Set Mode Linux', 'Configures DUT for Linux'))
                
        myPlan.append(QueryDiagFirmware(self, 'Query Firmware Revision', 'Query Firmware Revision'))
        
        myPlan.append(SetMode_LinuxDiags(self,'Set Mode Linux Diags', 'Configures DUT for LinuxDiags'))
        
        myPlan.append(ReportChassisConfig(self, 'Report chassis config', 'Report chassis config', timeout=15, ignoreErrors=True))
        
        myPlan.append(TemperatureTest(self,'Diag Temp Test', 'Hale temp sensor diagnostic test'))
        
        myPlan.append(TemperatureDump(self,'Diag Temp Dump', 'Temperature dump'))
                               
        myPlan.append(HVDriverOff(self,'HV Driver Off', 'HV Driver Off'))      

        myPlan.append(Delay(self,"Delay","Delay",delay=2.0))    
        
        myPlan.append(HVDriverOn(self,'HV Driver On', 'HV Driver On'))       

        #jamie - added back 'hv_driver screen all' for new Hales (firmware 4.10 or higher required)
        myPlan.append(HVDriverScreen(self,'HV Driver Test', 'HV Driver Test'))

        myPlan.append(PowerSeqTest(self,'Diag powerseq test', 'Diag powerseq test',timeout=20))
        
        myPlan.append(Delay(self,"Delay","Delay",delay=2.0))    
        
        myPlan.append(DiagCommandStep(self,'Diag powerseq', 'Diag powerseq', diagCmd='powerseq',timeout=120,ignoreErrors=True))
        
        myPlan.append(Delay(self,"Delay","Delay",delay=2.0))    
        
        myPlan.append(DiagCommandStep(self,'Diag powerseq voltages', 'Diag powerseq voltages', diagCmd='powerseq votages',timeout=120,ignoreErrors=True))
        
        myPlan.append(Delay(self,"Delay","Delay",delay=2.0))    

        myPlan.append(DiagCommandStep(self,'Diag Hotswap', 'Hotswap diagnostic test', diagCmd='hotswap',timeout=120,ignoreErrors=True))

        myPlan.append(PromTest(self,'Diag PROM', 'PROM diagnostic test', timeout=120))
                              
        print "Returning the Process Plan"
        return myPlan


def main():
    print "Building Process Plan"
    ec = []
    Plan = MainProcessPlan(ec)
    Plan.CreateProcessPlan()


if __name__ == "__main__":
    main()
