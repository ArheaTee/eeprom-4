'''
Created on July 19, 2016

@Developer: Navin T. (TDC-CTH)
'''

import httplib

class ODCServer(object):

    def __init__(self, cthmes, businessUnit):
        self.ODCConnection = None
        self.ODCDataValue  = ""
        self.businessUnit  = businessUnit
        self.cthmes        = cthmes
        
    def __del__(self):
        class_name = self.__class__.__name__

    ''' Connect to the ODC Server '''
    def connect(self,url=None):
        if url == None:
            url = self.cthmes
        self.ODCConnection = httplib.HTTPConnection(url,timeout=10)

    ''' Check the connection to ODC Server '''
    def check_connection(self):
        try:
            if self.requestData('/des/'+self.businessUnit+'/getparameter.asp?sn=12345678912&profile=getticket', 'GET'):
                return True
            else :
                return False
        except Exception as e:
            return False

    ''' Request data from the URL '''
    def requestData(self,url,method="GET"):
        try:
            if self.ODCConnection is not None:
                self.ODCConnection.request(method,url)
                res = self.ODCConnection.getresponse()
                if res.status == 200:
                    self.ODCDataValue = res.read()
                    return True
            return False
        except:
            return False

    ''' Get the data which is recieve from the ODC Server '''
    def getData(self):
        return self.ODCDataValue

    ''' Get the ticket from ODC Server for the input serial number '''
    def getTicket(self,serialNumber):
        self.connect(self.cthmes)
        if self.requestData('/des/'+self.businessUnit+'/getparameter.asp?sn='+serialNumber+'&profile=ticket', 'GET'):
            return self.ODCDataValue

    ''' Request the ticket from ODC Server for the input serial number '''
    def requestTicket(self,serialNumber):
        self.connect(self.cthmes)
        if self.requestData('/des/'+self.businessUnit+'/getticket.asp?sn='+serialNumber, 'GET'):
            return self.ODCDataValue
        
    ''' Clear the Ticket if you not process the data on the ODC server '''
    def clearTicket(self,serialNumber,ticketNumber):
        self.connect(self.cthmes)
        if self.requestData('/des/'+self.businessUnit+'/clearticket.asp?sn='+serialNumber+'&ticket='+ticketNumber, 'GET'):
            if "SUCCESS" in self.ODCDataValue:
                return True
        return False

    ''' Get the current station id for the input serial number '''
    def getCurrentStation(self,serialNumber):
        self.connect(self.cthmes)
        if self.requestData('/des/'+self.businessUnit+'/check.asp?sn='+serialNumber, 'GET'):
            return self.ODCDataValue

    ''' Get the profile parameter for the input serial number '''
    def getProfileParameter(self,serialNumber,profile):
        self.connect(self.cthmes)
        if self.requestData('/des/'+self.businessUnit+'/getparameter.asp?sn='+serialNumber+'&profile='+profile, 'GET'):
            return self.ODCDataValue

    ''' Send the ticket to ODC server for data processing '''
    def processData(self,ticket):
        self.connect(self.cthmes)
        if self.requestData('/des/'+self.businessUnit+'/process.asp?ticket='+ticket+'&process=true', 'GET'):
            if "SUCCESS" in self.ODCDataValue:
                return True
        print 'ODCServer processData response:\n{}'.format(self.ODCDataValue)
        return False

    ''' Send the XML data format to the ODC server '''
    def putData(self,method,pathUrl,data,header,server=None):
        if server == None:
            server = self.cthmes
        self.connect(server)
        header = {"content-type":header}
        self.ODCConnection.request(method,pathUrl,data,header)
        result = self.ODCConnection.getresponse()
        if result.status == 200:
            self.ODCDataValue = result.read()
            if "SUCCESS" in self.ODCDataValue:
                return True
        print 'ODCServer putData response:\n{}'.format(self.ODCDataValue)
        return False
        
if __name__ == '__main__':           
    ODCTest = ODCServer("10.196.100.17", "elm")
    ODCTest.connect()
    #print "Connected to ODC Server:",ODCTest.check_connection()
    #print "Get current station:",ODCTest.getCurrentStation("BBMCTH145000013")
    #if ODCTest.requestData('/des/spirent/getparameter.asp?sn=TESTDES001&profile=TECH-X_BFT', 'GET'):
    #    print ODCTest.getData()
    #print 'Get Parameter BOMFILE:', ODCTest.getProfileParameter('BBMCTH145000013','BOMFILE')
    #print 'Top level Part number:', ODCTest.getTopPN('BBMCTH145000013')
    #print 'Board level Part number:', ODCTest.getBoardPN('BBMCTH145000013')
    #print 'Board level Serial number:', ODCTest.getBoardSN('BBMCTH145000013')
    #print 'Get Existing Ticket Number:', ODCTest.getTicket('TQ3')

