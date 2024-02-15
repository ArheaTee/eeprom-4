import ConfigParser
import SerialComms
import os.path

class Driver(object):
    
    def __init__(self, ):
        self.parameters = dict()        
    
    def Initialize(self, ):
        self.ProcessConfigurationFile()
        self.DUT = SerialComms.DUT()    
        self.DUT.Initialize( self.parameters['DUTComPort'], self.parameters['DUTDebugOutput'], self.parameters['DUTSaveFailResponses'] )
        self.HumiditySensor = SerialComms.OmegaHumiditySensor()
        try:
            self.HumiditySensor.Initialize( self.parameters['HumiditySensorComPort'] )
        except:
            #do not error out if it is disconnected
            pass
        self.parameters["System Driver Initialized"] = True
        return
        
    def ProcessConfigurationFile(self):
        '''Reads in the Saybrook Charging System Configuration File and loads
        all values into the 'parameters' dictionary.
        '''

        self._config = ConfigParser.RawConfigParser()
        try:
            self._config.read(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'HaleFunctional.cfg'))  # Read in the Config File
                       
            self.parameters['DUTComPort'] = self._config.get('DUT_Comms','ComPort')
            self.parameters['DUTSaveFailResponses'] = self._config.getint('DUT_Comms','SaveFailResponses')
            self.parameters['DUTDebugOutput'] = self._config.getint('DUT_Comms','DebugOutput')
            self.parameters['HumiditySensorComPort'] = self._config.get('HumiditySensor_Comms','ComPort')
            try:
                self.parameters['SecondaryLogPath'] = self._config.get('Logging','SecondaryLogPath')
            except:
                pass
        except Exception as e1:
            err = 'The Following Error Occured Reading the System/System.cfg File '
            print('{} [ {}').format(err, str(e1))
            exit(1)
    
    
