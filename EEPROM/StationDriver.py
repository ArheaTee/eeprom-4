import threading
import os.path
import ConfigParser

class Driver(object):
    """
    This class provides the methods to interface with the resources on each station. The resources include
    the station valves and station vacum controller.
    """

    __dictLock = threading.RLock()

    def __init__(self, ):
        self.parameters = dict()
        return        

    def Initialize(self, station_index, parent_object):
        self.station_index = station_index
        self.whos_your_daddy = parent_object
        self.whos_your_daddy.parameters['station_'+str(station_index)] = "Initialized"
        self.parameters["Station Driver Initialized"] = True
        return

    def IncrementCycleCount(self, section, key):
        with Driver.__dictLock:
            filePath = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..', 'CycleCounts.cfg')
            if not os.path.isfile(filePath) :
                with open(filePath, "w"):
                    pass
            
            self._config = ConfigParser.RawConfigParser()            
            self._config.read(filePath)  # Read in the Config File
            try:
                cycleCount = self._config.getint(section, key) + 1
            except:
                cycleCount = 1
                            
            if not self._config.has_section(section):
                self._config.add_section(section)
            self._config.set(section, key, ("%d" % cycleCount))
            with open(filePath, "w") as configFile:
                self._config.write(configFile)
            return cycleCount
