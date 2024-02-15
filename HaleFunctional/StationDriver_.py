class Driver(object):
    """
    This class provides the methods to interface with the resources on each station. The resources include
    the station valves and station vacum controller.
    """

    def __init__(self, ):
        self.parameters = dict()
        return        

    def Initialize(self, station_index, parent_object):
        self.station_index = station_index
        self.whos_your_daddy = parent_object
        self.whos_your_daddy.parameters['station_'+str(station_index)] = "Initialized"
        self.parameters["Station Driver Initialized"] = True
        return
