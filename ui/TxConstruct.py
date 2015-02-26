from PyQt5.Qt import *
from PyQt5.QtGui import *
from PyQt5.QtNetwork import *
from qtdefines import *
from qtdialogs import createAddrBookButton, DlgSetComment, DlgSendBitcoins, \
                      DlgUnlockWallet, DlgQRCodeDisplay, DlgRequestPayment
from armoryengine.ALL import *
from armorymodels import *
from armoryengine.MultiSigUtils import MultiSigLockbox, calcLockboxID,\
   createLockboxEntryStr
from ui.MultiSigModels import \
            LockboxDisplayModel,  LockboxDisplayProxy, LOCKBOXCOLS
import webbrowser

         


#############################################################################
class TxInCtorEntry(object):
   def __init__(self, ustxi=None):
   
      if ustxi is None:
         ustxi = UnsignedTxInput()
   
      
      


#############################################################################
class DlgConstructTx(ArmoryDialog):

   #############################################################################
   def __init__(self, parent, main, prefill=None):
      super().__init__(parent, main)

      if prefill is None:
         prefill = UnsignedTransaction()


      if not TheBDM.getState()==BDM_BLOCKCHAIN_READY:
         LOGERROR('Cannot use tx ctor until Armory is in full online mode')
         self.reject()

      
      self.widgTableIn  = []
      self.widgTableOut = []
      self.txInSpendScript = []
      self.txInPrevScript = []
      self.txOut = []




   def addInputToTable(self, ustxi=None):

      if ustxi is None:
         ustxi = UnsignedTxInput()

      newRow = {}
      newRow['']


   def makeShortHRScriptFromBin(self, binScript):
      

   def makeShortHRScriptFromHex(self, hexScript):

   def makeShortHRScriptFromHR(self, hexScript):
      
   def humanScript_to(self, binScript=None, hexScript=None, humanScript=None):
      

   def updateTxInputScript(self, txinIndex, newScript):











