from ArmoryUtils import *
from ArmoryEncryption import *
from WalletEntry import *
from Timer import *


DEFAULT_LOOKAHEAD_LVL1  = 2   # look ahead 2 wallets
DEFAULT_LOOKAHEAD_LVL2  = 0   # look ahead 0 chains, we know ow many
DEFAULT_LOOKAHEAD_LVL3a = 500 # keep 500 ahead for receiving addrs
DEFAULT_LOOKAHEAD_LVL3b = 5   # look 5 ahead in "INTERNAL" wallet chains


# DECORATOR
# Decorator that allows us to pass ArmoryCryptInfo.encrypt/decrypt args
# to the function, and the wrapped function will use them to unlock the
# wallet before calling the function, and then relocking it afterwards.
def AcceptUnlockArgs(func):
   
   def wrappedFunc(*args, **kwargs):
      decryptArgs = {}
      for arg in ['kdfObj','ekeyObj','ivData','keyData']:
         if arg in kwargs:
            decryptArgs[arg] = kwargs[arg]
            del kwargs[arg]

      needToUnlockLock = len(decryptArgs) > 0
      if needToUnlockLock:
         args[0].getPrivCryptArgs
         

      if needToUnlockLock:
         

# DECORATOR
# Unlike the above, we are declaring that we need to separately unlock
# the relevant ekey(s) in the wallet before calling this function
def EkeyMustBeUnlocked(func):
   def wrappedFunc(*args, **kwargs):
      aekSelf = args[0]
      eid = aekSelf.privCryptInfo.keySource
      if self.cryptInfoObj.noEncryption():
         return mapOut



#class AddrGeneratingRoot(ArmoryExtendedKey):
#class RootGeneratingRoot(ArmoryExtendedKey):

################################################################################
################################################################################
class ArmoryWalletFile(object):

   def __init__(self):

      if not os.path.exists(filepath) and not createNew:
         LOGERROR('Attempted to open a wallet file that does not exist!')
         raise FileExistsError

      self.fileHeader = ArmoryFileHeader()

      # We will queue updates to the wallet file, and later apply them  
      # atomically to avoid corruption problems
      self.updateQueue   = []
      self.lastFilesize  = -1

      # WalletEntry objects may request an update, but that update is not 
      # applied right away.  This variable will be incremented on every
      # call to fsyncUpdates(), so WE objects know when it's done
      self.updateCount  = 0

      # We will need a bunch of different pathnames for atomic update ops
      self.walletPath        = self.getWalletPath('')
      self.walletPathBackup  = self.getWalletPath('backup')
      self.walletPathUpdFail = self.getWalletPath('update_unsuccessful')
      self.walletPathBakFail = self.getWalletPath('backup_unsuccessful')

      # Last synchronized all chains to this block
      self.lastSyncBlockNum = 0

      self.allWalletEntries = []
      self.siblingRoots = {}
      self.allRoots = {}

      # All wallet roots based on "standard" BIP 32 usage:
      #    rootMap[0] ~ Map of all zeroth-order roots, derived from seeds
      #    rootMap[1] ~ Map of all wallets for all base roots
      #    rootMap[2] ~ Map of internal/external chains of all wallets.
      # Maps are indexed by 20-byte ID (the address/hash160 they would have
      # if they were to be used to receive funds, but they are not in these
      # maps if they are ever used to receive funds -- all such addresses 
      # exist at the next level)
      self.rootMapBIP32 = [{}, {}, {}]

      # If there are other roots (such as old Armory wallets, or JBOK wlts,
      # etc) we will need to track them using other roots.  In the case of
      # old Armory wallets, the original index=-1 address will be included
      # in this map.  For importing old Bitcoin-Qt wallets, we will create 
      # a root with a random ID to hold "just a bunch of keys" (JBOK).
      self.rootMapOther = {}

      # Any lockboxes that are maintained in this wallet file
      # Indexed by p2sh-scrAddr
      self.lockboxMap = {}

      # List of all master encryption keys in this wallet (and also the 
      # data needed to understand how to decrypt them, probably by KDF)
      self.ekeyMap = {}

      # List of all KDF objects -- probably created based on testing the 
      # system speed when the wallet was created
      self.kdfMap  = {}

      # Maps relationship IDs to relationship objects
      self.relationshipMap  = {}

      # Master address list of all wallets/roots/chains that could receive BTC
      self.masterAddrMap  = {}

      # List of all encrypted wallet entries that couldn't be decrypted 
      # Perhaps later find a way decrypt and put them into the other maps
      self.opaqueList  = []

      # List of all WalletEntry objects that had a file code we didn't 
      # recognize.  Perhaps these were created by a newer version of
      # Armory, or will be consumed by a module/plugin
      self.unrecognizedList  = []

      # List of all WalletEntry objects that had an unrecoverable error
      self.unrecoverableList  = []

      # List of all WalletEntry objects that had an unrecoverable error
      self.wltParentMissing  = []

      # We have the ability to store arbitrary data in the wallet files
      # Among other things, this gives plugins a way to read and write
      # data to wallet files, and running Armory without the plugin will
      # just shove it into this map and ignore it.
      self.arbitraryDataMap = {}

      # List of all WalletEntry object IDs disabled for various reasons
      # (usually from critical data not recognized in a child entry)
      self.disabledEntries = set()
      self.disabledList = []

      # If != None, it means that this wallet holds only a subset of data 
      # in the parent file.  Probably just addr/tx comments and P2SH scripts
      self.masterWalletRef = None

      # Alternatively, if this is a master wallet it may have a supplemental
      # wallet for storing
      self.supplementalWltPath = None
      self.supplementalWltRef = None

      # Default encryption settings for "outer" encryption (if we want to
      # encrypt the entire WalletEntry, not just the private keys
      self.defaultOuterEncrypt = ArmoryCryptInfo(None)
      self.defaultInnerEncrypt = ArmoryCryptInfo(None)

      # This file may actually be used for a variety of wallet-related 
      # things -- such as transferring observer chains, exchanging linked-
      # wallet info, containing just comments/labels/P2SH script -- but 
      # not actually be used as a proper wallet.
      self.isTransferWallet = False
      self.isSupplemental = False


      # These flags are ONLY for unit-testing the atomic file operations
      self.interruptTest1  = False
      self.interruptTest2  = False
      self.interruptTest3  = False

      # Set read-only flag:  will not modify any wallet files, will not 
      # create backup, will throw error if you attempt to write anything.
      # Really, this is intended for reading and querying the wallet obj.
      # Even generating new addresses would induce file write ops.
      self.isReadOnly = False


      # Wallet operations are not threadsafe.  Detect multiple access
      self.midWriteFlag = threading.Event()


   #############################################################################
   def createNewKDFObject(self, kdfAlgo, writeToFile=True, **kdfCreateArgs):
      """
      ROMixOv2 is ROMix-over-2 -- it's the ROMix algorithm as described by 
      Colin Percival, but using only 1/2 of the number of LUT ops, in order
      to bring down computation time in favor of more memory usage.

      If we had access to Scrypt, it could be an option here.  ROMix was 
      chosen due to simplicity despite its lack of flexibility
      """
      LOGINFO('Creating new %s KDF with the following parameters:' % kdfAlgo)
      for key,val in kdfCreateArgs.iteritems():
         LOGINFO('   %s: %s' % (key, str([val]))
         
      newKDF = KdfObject.createNewKDF(kdfAlgo, **kdfCreateArgs)
      self.kdfMap[newKDF.getKdfID()] = newKDF

      if writeToFile:
         self.doFileOperation('Append', newWE)


   
         
   #############################################################################
   def changeMasterKeyEncryptParams(self, ekeyID, oldParams, newParams):
      # We can either change encryption or kdf params of a single password,
      # or switch from single-password to multi-password or back.  To switch
      # types of password protection, we'll need to write the new entry and 
      # then delete the old one.
      raise NotImplementedError

   #############################################################################
   def changeOuterEncryption(self, encryptInfoObj):
      raise NotImplementedError

   #############################################################################
   def findAllEntriesUsingObject(self, objID):
      """
      Use this to identify whether certain objects, such as KDF objects, are 
      no longer being used and can be removed (or for some other reason)
      """
      raise NotImplementedError

   #############################################################################
   def getKDF(self, kdfID):
      return self.kdfMap.get(kdfID, None)

   #############################################################################
   def getEkey(self, ekeyID):
      return self.ekeyMap.get(ekeyID, None)

   #############################################################################
   def mergeWalletFile(self, wltOther, rootsToAbsorb='ALL'):
      """
      Just like in git, WltA.mergeWalletFile(WltB) means we want to pull all 
      the data from WltB into WltA and leave WltB untouched.
      """

      if isinstance(wltOther, basestring):
         # Open wallet file
         if not os.path.exists(wltOther):
            raise WalletExistsError('Wallet to merge DNE: %s' % wltOther)
         wltOther = ArmoryWalletFile.readWalletFile(filepath, openReadOnly=True)


      '''
      rootRefList = []

      #
      for level in range(3):
         rootMap = wltOther.rootMap[level]
         for rootID,root in rootMap.iteritems():
            if rootsToAbsorb=='ALL' or rootID in rootsToAbsorb:
               rootRefList.append(rootID, root)



      # We need to not only copy over all addr and sub-roots, but
      # also all KDF objects and any other things in the file that ref
      # this root/addr (also any relationship objects and any roots
      # related to that, as well)
      i = 0
      procRootAlready = set([])
      while i<len(rootRefList):
         rootID,root = rootRefList[i]
         if rootID in procRootAlready:
            continue

         procRootAlready.add(rootID)

         
         addFileOperationToQueue

         if root.relationship.isForMultisig:
            # Make sure to merge the sibling wallets, too
            for sib in root.relationship.siblingList:
               if not sib.rootID in rootRefList:
                  LOGINFO('Adding sibling to root-merge list')
               rootRefList.add(sib.rootID)

      '''



   #############################################################################
   def mergeRootFromWallet(self, filepath, rootID, weTypesToMerge=['ALL']):
      # Open wallet file
      if not os.path.exists(filepath):
         LOGERROR('Wallet to merge does not exist: %s', filepath)

      with open(filepath, 'rb') as f:
         bu = BinaryUnpacker(f.read())

      while not bu.isEndOfStream():
         weObj = readWalletEntry(bu)
         if weObj.payload.root160:
            raise 'Notimplemented'   
         if weTypesToMerge[0].lower()=='all' or weObj.entryCode in weTypesToMerge:
            self.addFileOperationToQueue('Append', weObj)
      

   #############################################################################
   def loadExternalInfoWallet(self, filepath):
      """
      After this wallet is loaded, we may want to merge, in RAM only, another
      wallet file containing only P2SH scripts and comments.  The reason for
      this is that our root private key only needs to be backed up once, but 
      P2SH scripts MUST be backed up regularly (and comment fields would be 
      nice to have backed up, too).  The problem is, you don't want to put 
      your whole wallet file into dropbox, encrypted or not.  The solution is
      to have a separate P2SH&Comments file (a wallet without any addresses)
      which can be put in Dropbox.  And encrypt that file with information
      in the wathcing-only wallet -- something that you have even without 
      unlocking your wallet, but an attacker does not if they compromise your
      Dropbox account.
      """
      raise NotImplementedError

      if not exists(filepath):
         LOGERROR('External info file does not exist!  %s' % filepath)

      self.externalInfoWallet =  ArmoryWalletFile.ReadWalletFile(filepath)


   #############################################################################
   def readWalletEntry(self, toUnpack):
      we = WalletEntry().unserialize(toUnpack)


   #############################################################################
   @staticmethod
   def ReadWalletFile(wltPath, openReadOnly=False, **outerCryptArgs):
      """
      This reads an Armory wallet 2.0 wallet file, which contains a constant-
      size header, and then a collection of IFF/RIFF-like WalletEntry objects.
      
      WE DO NOT ASSUME ANY PARTICULAR ORDERING!  For instance, if a WalletEntry
      object references a KDF object that is in the same wallet file, we never
      assume that the KDF object has been read yet.  While we may enforce
      reasonable ordering when we create the wallet, there are certain wallet
      operations (like mergine wallets) which may leave them out of order.  

      For that reason, this method has two phases: 
         (1) Read and organize all the WalletEntry objects into maps/lists
         (2) Walk through all the objects and do anything that requires 
             references to other objects in the wallet file, such as setting
             child-parent references, and disabling nodes with critical
             children that are unrecognized

      In case there are outer-encrypted entries in the wallet (all info
      about the WalletEntry is encrypted except for the parent ID), then 
      we will repeat the above after decrypting the opaque objects.
      """
      if not os.path.exists(wltPath):
         raise FileExistsError('Wallet file does not exist: %s' % wltPath)


      wlt = ArmoryWalletFile()
      wlt.walletPath = wltPath
      wlt.isReadOnly = openReadOnly
   
      if openReadOnly:
         if not wlt.checkWalletIsConsistent():
            raise WalletUpdateError('Wallet to open in RO mode is inconsistent!')
      else:
         wlt.doWalletFileConsistencyCheck()

      # We assume the raw wallet fits in RAM.  This isn't a bad assumption,
      # since the wallet file is currently designed to hold all wallet entries
      # in RAM anyway.  If we want to change this, we need to switch to a 
      # database-backed wallet design.
      openfile = open(wltPath,'rb')
      rawWallet = BinaryUnpacker(openfile.read())
      openfile.close()

      
      # The header is always the first X bytes.  Check the
      wlt.fileHeader = ArmoryFileHeader.Unserialize(rawWallet)
      if wlt.fileHeader.isDisabled:
         wlt.isDisabled = True
         return wlt

      allEntries = [] 
      while rawWallet.getRemainingSize() > 0:
         currPos = rawWallet.getPosition()
         wltEntry = WalletEntry.UnserializeEntry(rawWallet, wlt, currPos)
         allEntries.append(wltEntry)
         
         
      # This will organize all the entries into their respective lists/maps,
      # set references between related objects, disable things as needed, etc
      wlt.addEntriesToWallet(allEntries)


      # If outer encryption was used on any entries, decrypt & add, if possible
      # (needed to add previous entries, because one is probably the decryption
      # key and/or KDF needed to unlock outer encryption)
      if len(wlt.opaqueList) > 0:
         if len(outerCryptArgs) == 0:
            LOGWARN('Opaque entries in wallet, no decrypt args supplied')
         else:
            newWEList = []
            for we in wlt.opaqueList:
               newWEList.append(we.decryptPayloadReturnNewObj(**outerCryptArgs))

            wlt.addEntriesToWallet(newWEList)
            wlt.opaqueList = []
         

      # The wallet is now ready for use
      return wlt



   #############################################################################
   def addEntriesToWallet(self, weList):
      """
      This operates in two steps:  
         (1) Filter the list of WalletEntry objects into the right lists/maps
         (2) Go back through everything and set references between them and 
             apply any operations that requires having all WE objects avail 
             (such as disabling parents of unrecognized-but-critical children,
             linking multi-sig roots based on relationship objects, etc)
             
      Everything that will be accessed by ID is stored in a map indexed by
      ID.  For now, we will assume that all parent references are ArmoryRoot
      objects (or None), and everything else will know which map to look in
      (like looking in ekeyMap when looking for encryption keys).  Therefore,
      we do not store a master map of all IDs.
      """
      
      for we in weList:
         if we.isDeleted:  
            continue


         # In case the Reed-Solomon error correction actually finds an error
         if we.needRewrite and not openReadOnly:
            self.addFileOperationToQueue('UpdateEntry', we)

         # If WE is unrecognized, ignore, if also critical, disable parent
         if we.isUnrecognized:
            self.unrecognizedList.append(we)
            if we.isRequired:
               self.disabledEntries.add(we.parent160)
            continue

         if we.isUnrecoverable:
            self.unrecoverableList.append(we)
            continue
      
         if we.isOpaque:
            self.opaqueList.append(we)
            continue

         # Everything else goes in the master list of entries
         self.allWalletEntries.append(we)

         # We explicitly don't use isinstance here, because it's easy to
         # mess up derived classes, which will fall into conditional
         # branches you weren't expecting
         if we.FILECODE=='ROOT':
            weID = we.getEntryID()
            if weID in self.allRoots:
               LOGWARN('Armory root is in wallet file multiple times!')
            self.allRoots[weID] = we
         if we.FILECODE=='AEK_':
            self.masterAddrMap[we.getScrAddr()] = we
         elif we.FILECODE=='RLAT':
            self.relationshipMap[we.relID] = we
         elif we.FILECODE=='ALBL':
            self.allLabels[we.scrAddr] = we
         elif we.FILECODE=='TLBL':
            if we.txidFull: 
               self.allLabels[we.txidFull] = we
            if we.txidMall: 
               self.allLabels[we.txidMall] = we
         elif we.FILECODE=='LBOX':
            self.lockboxMap[we.lboxID] = we
         elif we.FILECODE in ['EKEY','MKEY']:
            self.ekeyMap[we.ekeyID] = we
         elif we.FILECODE=='KDF_':
            self.kdfMap[we.kdfObjID] = we
         elif we.FILECODE=='DATA':
            self.arbitraryDataMap[we.dataName] = we
         

      # Set parent-child references for wallet entries' root vars
      for i,we in enumerate(self.allWalletEntries):
         wltParent = self.allRoots.get(we.wltParentRef)
         if wltParent is None:
            self.wltParentMissing.append(we)
            del self.allWalletEntries[i]
            continue
         
         we.wltParentRef = wltParent 
         wltParent.wltChildRefs.append(we)

         # AEK objects actually have a separate DAG structure for 
         # relating keys to other keys, that is different from the
         # relationships defined at the WalletEntry level
         if isinstance(we, ArmoryExtendedKey):
             
         
            
      # Set Ekey and KDF references
      for i,we in enumerate(self.allWalletEntries):
         
         if we.FILECODE == 'EKEY':
            kdfid = we.keyCryptInfo.kdfObjID
            ekeyKdf = self.kdfMap.get(kdfid)
            if ekeyKdf is None:
               LOGERROR('KDF %s for Ekey %s is not available' % \
                  binary_to_hex(kdfid), binary_to_hex(we.ekeyID))
               continue
            we.setKdfObjectRef(ekeyKdf)
         elif we.FILECODE == 'MKEY':
            # We set multiple KDFs from the wallet file for each multi-pwd key
            kdfList = []
            for einfo in we.einfos:
               kdfid = einfo.kdfObjID
               ekeyKdf = self.kdfMap.get(kdfid)
               if ekeyKdf is None:
                  LOGERROR('KDF %s for Ekey %s is not available' % \
                     binary_to_hex(kdfid), binary_to_hex(we.ekeyID))
               continue
               kdfList.append(ekeyKdf)
            we.setKdfObjectRefList(kdfList)
         elif isinstance(we, ArmoryExtendedKey):
            ekid = we.privCryptInfo.keySource
            ekey = self.ekeyMap.get(ekid)
            if ekey is None:
               LOGERROR('Ekey not in wallet file: %s' % binary_to_hex(ekid))
               continue
            we.masterEkeyRef = ekey


            
      # Aggregate roots that are part of multi-sig transactions
      for root in self.allRoots:
         if not isinstance(root, MultisigRoot):
            continue

         if not root.isComplete:
            continue

         for sib160 in root.sib160s:
            sibRoot = self.allRoots.get(sib160)
            if sibRoot is None: 
               LOGWARN('Disabling multisig root b/c could not find sib root')
               self.disabledEntries.append(root.getEntryID())
               break

            root.setSiblingRef(self, sibRoot):
            sibRoot.isForMultisig = True


      # First look for all children that have been marked to be disabled
      # Mark their wltParent parents to be disabled
      for node in self.allRoots:
         if node.getEntryID() in self.disabledEntries or
            node.wltParentRef.getEntryID() in self.disabledEntries:
            node.isDisabled = True 
            self.disabledList.append(node)
            del self.allRoots[nodeID]
            
      # Then recursively disable all children of disabled roots
      for node in self.disabledList:
         node.disableAllWltChildren()
         
      # TODO: due to complexity, did not remove disabled children from
      #       their respective lists, but I believe all that matters is
      #       that the roots have been removed.  Need to test this.
               
         
      if not self.isReadOnly:
         self.fsyncUpdates()

      return wlt

      #self.rootMapBIP32 = [{}, {}, {}]
      #self.rootMapOther = {}
      #self.lockboxMap = {}
      #self.ekeyMap = {}
      #self.kdfMap  = {}
      #self.relationshipMap  = {}
      #self.masterAddrMap  = {}
      #self.arbitraryDataMap = {}
      #self.opaqueList  = []
      #self.unrecognizedList  = []
      #self.unrecoverableList  = []
      #self.disabledEntries = set()

      #'ROOT', ArmoryRoot, ISREQUIRED)
      #'ALBL', AddressLabel)
      #'TLBL', TxLabel)
      #'LBOX', MultiSigLockbox)
      #'RLAT', RootRelationship, ISREQUIRED)
      #'EKEY', EncryptionKey)
      #'MKEY', MultiPwdEncryptionKey)
      #'KDF_', KdfObject)
      #'IDNT', IdentityPublicKey)
      #'SIGN', WltEntrySignature)
      #'DATA', ArbitraryDataContainer)
         
      

   #############################################################################
   def doFileOperation(self, operationType, theData, loc=None):
      """
      This is intended to be used for one-shot safe writing to file. 
      Normally, you would batch your updates using addFileOperationToQueue
      and then call fsyncUpdates() when you're done.
      """
      if not len(self.updateQueue)==0:
         LOGERROR('Wallet update queue not empty!  Adding this to the')
         LOGERROR('queue and ')

      self.addFileOperationToQueue(operationType, theData, loc)
      self.fsyncUpdates()
          

   #############################################################################
   @VerifyArgTypes(operationType=str, wltEntry=[WalletEntry, ArmoryFileHeader])
   def addFileOperationToQueue(self, operationType, wltEntry)
      """
      This will add/update/delete a wallet entry . 
      batch operation.  
      a shortcut method for operating with WalletEntry objects.

          ('RewriteHeader', ArmoryFileHeader)
          ('AddEntry',      WalletEntryObj)
          ('UpdateEntry',   WalletEntryObj)
          ('DeleteEntry',   WalletEntryObj)

      If one of the "entry" versions is used, it will simply pull the
      necessary information out of the object and do an "Append' or "Modify'
      as necessary.
      """
      if self.isReadOnly:
         raise WalletUpdateError('Cannot do file ops on ReadOnly wallet!')

      if not operationType.lower() in ['rewriteheader','addentry', 
                                       'updateentry', 'deleteentry']:
         raise BadInputError('Wallet update type invalid: %s' % operationType)
      
      self.updateQueue.append([operationType, wltEntry])
      wltEntry.needsFsync = True
         
      '''
      # The data to eventually be added to the file, or overwrite previous data
      serData = None

      # Convert the "___Entry" commands into the lower-level Append/Modify cmds
      if operationType.lower()=='addentry':
         # Add a new wallet entry to this wallet file
         if wltEntry.wltByteLoc >= 0:
            return   # Already in the wallet
         operationType = 'Append'
         serData = we.serialize()
      elif operationType.lower()=='updateentry':
         # Update an existing entry -- delete and append if size changed
         # wltEntrySz is the size of the WE when it was last read from 
         # the wallet file.  If its size has changed, its serialized size
         # will be different than that
         serData = we.serialize()
         if len(we.serializeEntry())==we.wltEntrySz:
            fileLoc = we.wltStartByte
            operationType = 'Modify'
         else:
            LOGINFO('WalletEntry replace != size (%s).  ', we.entryCode)
            LOGINFO('Delete&Append')
            self.addFileOperationToQueue('DeleteEntry', we.wltStartByte)
            operationType = 'Append'
      elif operationType.lower()=='deleteentry':
         # Delete an entry from the wallet
         fileLoc = we.wltStartByte 
         if not isinstance(we, (int,long)):
            LOGERROR('Delete entry only using WltEntry object or start byte')
            return

         delBytes = wltEntrySz
         serData = ZeroData(delBytes).serialize()
         operationType = 'Modify'

         # We already know that the entry is going away, set the start byte now
         we.wltStartByte = -1
         we.wltEntrySz = -1


      #####
      # This is where it actually gets added to the queue.
      if operationType.lower()=='append':
         if isWltEntryObj:
            we.wltStartByte =  self.lastFilesize
         self.lastFilesize += len(serData)
         self.updateQueue.append([WLT_UPDATE_ADD, serData])
      elif operationType.lower()=='modify':
         if not fileLoc:
            LOGERROR('Must supply start byte of modification')
            raise BadInputError
         self.updateQueue.append([WLT_UPDATE_MODIFY, [serData, fileLoc]])

      #####
      # Tell the WalletEntry object when to expect its internal state to be 
      # consistent with the wallet file
      if isWltEntryObj:
         we.syncWhenUpdateCount = self.updateCount + 1
      '''
         
         

   #############################################################################
   def getWalletPath(self, nameSuffix=None):
      fpath = self.walletPath

      if self.walletPath=='':
         fpath = os.path.join(ARMORY_HOME_DIR, 'armory_wallet_%s.bin' % self.uniqueIDB58)

      if nameSuffix:
         name,ext = os.path.splitext(fpath)
         joiner = '' if name.endswith('_') else '_'
         fpath = name + joiner + nameSuffix + ext
      return fpath


   #############################################################################
   def fsyncUpdates(self):
            
      """
      When we want to add data to the wallet file, we will do so in a completely
      recoverable way.  We define this method to make sure a backup exists when
      we start modifying the file, and keep a flag to identify when the wallet
      might be corrupt.  If we ever try to load the wallet file and see another
      file with the _update_unsuccessful suffix, we should instead just restore
      from backup.

      Similarly, we have to update the backup file after updating the main file
      so we will use a similar technique with the backup_unsuccessful suffix.
      We don't want to rely on a backup if somehow *the backup* got corrupted
      and the original file is fine.  THEREFORE -- this is implemented in such
      a way that the user should know two things:
      """
      if self.isReadOnly:
         raise WalletUpdateError('Wallet is opened in read-only mode!')

      if self.midWriteFlag.isSet():
         raise MultiThreadingError( \
            'Attempted to call fsync while currently fsync\'ing.  This is'
            'probably a multithreading collision.  Wallet operations are'
            'not threadsafe!')
      
      
      if len(self.updateQueue)==0:
         return False

      
      try:
         if not os.path.exists(self.walletPath):
            raise FileExistsError, 'No wallet file exists to be updated!'
   
         # Identify if the batch contains updates to the same object mult times.
         # We can safely batch updates to any mixture of objects, but not 
         # multiple changes to the same object
         fileLocToUpdate = set()
         for opType,weObj in self.updateQueue:
            if weObj.wltByteLoc in fileLocToUpdate:
               LOGERROR('Obj: %s (ID=%s, loc=%d)', weObj.FILECODE, 
                           binary_to_hex(weObj.uniqueID, weObj.wltByteLoc)
               raise WalletUpdateError('Multiple updates to same ID in batch')
            fileLocToUpdate.add(weObj.wltByteLoc)
   
         # Make sure that the primary and backup files are synced before update
         self.doWalletFileConsistencyCheck()
   
         # Make sure all entries have valid wallet file locations
         for opType,weObj in self.updateQueue:
            if opType in ['updateentry', 'deleteentry'] and weObj.wltByteLoc <= 0:
               raise WalletUpdateError('Wallet entry cannot be updated without loc')
        
         # Apply updating to both files in an identical manner
         MAIN,BACKUP = [0,1]
         for fnum in [MAIN,BACKUP]:
            # Update fail flags so that if process crashes mid-update, we know
            # upon restart where it failed and can recover appropriately
            if fnum==MAIN:
               # Modify the main wallet file, set flag to indicate we started
               wltPath = self.walletPath
               interrupt = self.interruptTest1
               touchFile(self.walletPathUpdFail)
            elif fnum==BACKUP:
               # +flag to start modifying backup file, -flag bc MAIN updating done
               wltPath = self.walletPathBackup
               interrupt = self.interruptTest3
               touchFile(self.walletPathBakFail)
               if self.interruptTest2: raise InterruptTestError 
               os.remove(self.walletPathUpdFail)
               
   
            # We will do all mid-file operations first, and queue up all 
            # append operations for the end.  Second pass will apply all the 
            # append operations and then update the weObjs with new size and 
            # loc. Append operations include both the AddEntry cmds in the 
            # queue, also UpdateEntry cmds with objects now a different size.
            appendAfterOverwriteQueue = []
   
            try:
               writefile = open(wltPath, 'r+b')
            except IOError:
               LOGEXCEPT('Failed to open %s in r+b mode. Permissions?' % wltPath)
               return False
   
            for opType,weObj in self.updateQueue:
               # At this point, self.wltEntrySz is always the size of the 
               # object currently in the file, not yet been updated if the WE 
               # is now a new size.  If we requested "UpdateEntry" but we 
               # serialize the object and it turns out to be a different size,   
               # then we delete and append, instead.
               if opType.lower()=='rewriteheader':
                  # Header is always exact same size, at beginning of file
                  wltfile.seek(0)
                  wltfile.write(weObj.serialize())
               elif opType.lower() == 'addentry':
                  # Queue up append operations until after in-place modifications
                  appendAfterOverwriteQueue.append([weObj, weObj.serializeEntry()])
               elif opType.lower() == 'deleteentry':
                  # Delete is just in-place modification, overwrite with \x00's
                  weObj.isDeleted = True
                  wltfile.seek(weObj.wltByteLoc)
                  wltfile.write(weObj.serialize())
               elif opType.lower() == 'updateentry':
                  weSer = weObj.serializeEntry()
                  if len(weSer) == weObj.wltEntrySz:
                     # Same size, overwrite in-place
                     wltfile.seek(weObj.wltByteLoc)
                     wltfile.write(weObj.serialize())
                  else:
                     # Obj changed size, delete old add new one to the queue
                     wltfile.seek(weObj.wltByteLoc)
                     wltfile.write(weObj.serializeEntry(doDelete=True))
                     appendAfterOverwriteQueue.append([weObj, weSer])
   
            # This is for unit-testing the atomic-wallet-file-update robustness
            if interrupt: raise InterruptTestError
   
            # Close file for writing, reopen it in append mode
            try:
               writefile.close()
               appendFile = open(wltPath, 'ab')
            except IOError:
               LOGEXCEPT('Failed to open %s in ab mode. Permissions?' % wltPath)
               return False
   
            for weObj,weSer in appendAfterOverwriteQueue:
               appendfile.write(weSer)
               # At end of updating backup file, can update WE objects
               if fnum==BACKUP:
                  weObj.wltEntrySz = len(weSer)
                  weObj.wltByteLoc = appendfile.tell() - weObj.wltEntrySz
         
            appendfile.close()
   
         # Finish by removing flag that indicates we were modifying backup file
         os.remove(self.walletPathBakFail)
   
         # Mark WalletEntry objects as having been updated
         for opType,weObj in self.updateQueue:
            weObj.needsFsync = False
   
         # In debug mode, verify that main and backup are identical
         if CLI_OPTIONS.doDebug:
            hashMain = sha256(open(self.walletPath,       'rb').read())
            hashBack = sha256(open(self.walletPathBackup, 'rb').read())
            if not hashMain==hashBack:
               raise WalletUpdateError('Updates of two wallet files do not match!')
   
         return True
      finally:
         self.midWriteFlag.clear()
         
   
   
   

   #############################################################################
   def doWalletFileConsistencyCheck(self, onlySyncBackup=True):
      """
      First we check the file-update flags (files we touched/removed during
      file modification operations), and then restore the primary wallet file
      and backup file to the exact same state -- we know that at least one of
      them is guaranteed to not be corrupt, and we know based on the flags
      which one that is -- so we execute the appropriate copy operation.

      ***NOTE:  For now, the remaining steps are untested and unused!

      After we have guaranteed that main wallet and backup wallet are the
      same, we want to do a check that the data is consistent.  We do this
      by simply reading in the key-data from the wallet, unserializing it
      and reserializing it to see if it matches -- this works due to the
      way the PyBtcAddress::unserialize() method works:  it verifies the
      checksums in the address data, and corrects errors automatically!
      And it's part of the unit-tests that serialize/unserialize round-trip
      is guaranteed to match for all address types if there's no byte errors.

      If an error is detected, we do a safe-file-modify operation to re-write
      the corrected information to the wallet file, in-place.  We DO NOT
      check comment fields, since they do not have checksums, and are not
      critical to protect against byte errors.
      """

      if not os.path.exists(self.walletPath):
         raise FileExistsError('No wallet file exists to be checked!')

      walletFileBackup = self.getWalletPath('backup')
      mainUpdateFlag   = self.getWalletPath('update_unsuccessful')
      backupUpdateFlag = self.getWalletPath('backup_unsuccessful')

      if not os.path.exists(walletFileBackup):
         # We haven't even created a backup file, yet
         LOGDEBUG('Creating backup file %s', walletFileBackup)
         touchFile(backupUpdateFlag)
         shutil.copy(self.walletPath, walletFileBackup)
         os.remove(backupUpdateFlag)

      if os.path.exists(backupUpdateFlag) and os.path.exists(mainUpdateFlag):
         # Here we actually have a good main file, but backup never succeeded
         LOGERROR('***WARNING: error in backup file... how did that happen?')
         shutil.copy(self.walletPath, walletFileBackup)
         os.remove(mainUpdateFlag)
         os.remove(backupUpdateFlag)
      elif os.path.exists(mainUpdateFlag):
         LOGERROR('***WARNING: last file operation failed!  Restoring wallet from backup')
         # main wallet file might be corrupt, copy from backup
         shutil.copy(walletFileBackup, self.walletPath)
         os.remove(mainUpdateFlag)
      elif os.path.exists(backupUpdateFlag):
         LOGERROR('***WARNING: creation of backup was interrupted -- fixing')
         shutil.copy(self.walletPath, walletFileBackup)
         os.remove(backupUpdateFlag)

      if onlySyncBackup:
         return 0

   #############################################################################
   def checkWalletIsConsistent(self):
      """
      Same as doWalletFileConsistencyCheck, but does not modify anything.
      Instead, returns False if there is an inconsistency that would otherwise
      induce wallet changes by doWalletFileConsistencyCheck
      """

      if not os.path.exists(self.walletPath):
         raise FileExistsError('No wallet file exists to be checked!')

      walletFileBackup = self.getWalletPath('backup')
      mainUpdateFlag   = self.getWalletPath('update_unsuccessful')
      backupUpdateFlag = self.getWalletPath('backup_unsuccessful')

      if not os.path.exists(walletFileBackup):
         # No backup file to compare against
         return True
      elif os.path.exists(backupUpdateFlag) and os.path.exists(mainUpdateFlag):
         # Here we actually have a good main file, but backup never succeeded
         return False
      elif os.path.exists(mainUpdateFlag):
         return False
      elif os.path.exists(backupUpdateFlag):
         return False

      return True

   #############################################################################
   @VerifyArgTypes(securePwd=SecureBinaryData,
                   extraEntropy=[SecureBinaryData, None],
                   preGenSeed=[SecureBinaryData, None])
   def generateNewSinglePwdSeedEkeyKDF(self, securePwd, kdfAlgo='ROMIXOV2',
                                       kdfTargSec=0.25, kdfMaxMem=32*MEGABYTE,
                                       encrAlgo='AES256CBC', extraEntropy=None,
                                       preGenSeed=None):
      
   
      LOGINFO('Creating new single-password wallet seed')

      LOGINFO('Creating new KDF with params: time=%0.2fs, maxmem=%0.2fMB', 
                                        kdfTargSec, kdfMaxMem/float(MEGABYTE))

      newKdf = KdfObject.createNewKDF(kdfAlgo, kdfTargSec, kdfMaxMem)

      tstart = RightNow()
      newKdf.execKDF(SecureBinaryData('TestPassword'))
      tend = RightNow()

      LOGINFO('KDF ID=%s uses %0.2fMB and a test password took %0.2fs',
                     binary_to_hex(newKdf.getKdfID()), 
                     newKdf.memReqd/float(MEGABYTE), (tend-tstart))

      
      LOGINFO('Creating new master encryption key')
      newEkey = EncryptionKey().createNewMasterKey(newKdf, encrAlgo, securePwd)
      LOGINFO('New Ekey has ID=%s',  binary_to_hex(newEkey.ekeyID))

      
      # Copy all sensitive data into newSeed and destroy at the end.  If a SBD
      # object was created to be passed into pregen arg, caller can destroy it.
      if preGeneratedSeed is None:
         if extraEntropy is None:
            raise KeyDataError('Need extra entropy for secure seed creation')
         newSeed = SecureBinaryData().GenerateRandom(32, extraEntropy)
      else:
         newSeed = preGeneratedSeed.copy()


      newRoot = ArmoryRoot().createNewRootFromSeed(seed=newSeed)
      
      
      self.addFileOperationToQueue('AddEntry', newKdf)
      self.addFileOperationToQueue('AddEntry', newEkey)
      self.addFileOperationToQueue('AddEntry', newRoot)
      self.fsyncUpdates()
      
      

   #############################################################################
   @VerifyArgTypes(extraEntropy=[SecureBinaryData, None],
                   preGeneratedSeed=[SecureBinaryData, None])
   def createAndAddNewMasterRoot(self, extraEntropy, encryptInfo, 
                                       preGeneratedSeed=None, **cryptKwArgs):
      """
      If this new master seed is being protected with encryption that isn't
      already defined in the wallet, then the new Ekey & KDF objects needs 
      to be created and added to the wallet before calling this function.  
      The **cryptKwArgs will be passed to the ACI:
         
         encryptInfo.encrypt(newSeed, **cryptKwArgs)
   
      Thus, it should contain everything that is needed to do the master 
      seed encryption.  If it's password encryption only, then it should
      include a KDF and a password.  If it's master-key encryption, should 
      include the master ekeyObj and the password(s) with which it is encrypted
      
      "extraEntropy" is a required argument here, because we should *always*
      be sending extra entropy into the secure (P)RNG for seed creation.  
      Never fully trust the operating system, and there's no way to make its 
      seed generation worse, so we will require it even if the caller decides
      to pass in all zero bytes.  ArmoryQt.getExtraEntropyForKeyGen() (as 
      of this writing) provides a 32-byte SecureBinaryData object which is 
      the hash of system files, key- and mouse-press timings, and a screenshot 
      of the user's desktop.

      Note if you pass in a pregenerated seed, you can then pass in None for 
      extraEntropy arg
      """


      # Copy all sensitive data into newSeed and destroy at the end.  If a SBD
      # object was created to be passed into pregen arg, caller can destroy it.
      if preGeneratedSeed is None:
         if extraEntropy is None:
            raise KeyDataError('Need extra entropy for secure seed creation')
         newSeed = SecureBinaryData().GenerateRandom(32, extraEntropy)
      else:
         newSeed = preGeneratedSeed.copy()


      
      try:
         cryptSeed = encryptInfo.encrypt(newSeed, **cryptKwArgs)
         self.addPregeneratedMasterSeed(newSeed, cryptSeed)

      finally:
         LOGEXCEPT('Error during seed creation and addition to wallet')
         newSeed.destroy()
      
       


      

   #############################################################################
   def unlockWalletEkey(self, ekeyID, **unlockArgs):
      ekeyObj = self.ekeyMap.get(ekeyID, None)

      if ekeyObj is None:
         raise KeyDataError("No ekey in wlt with id=%s" % binary_to_hex(ekeyID))

      ekeyObj.unlock(**unlockArgs)

   #############################################################################
   def lockWalletEkey(self, ekeyID):
      # Lock this specific ekey
      ekeyObj = self.ekeyMap.get(ekeyID, None)
      if ekeyObj is None:
         raise KeyDataError("No ekey in wlt with id=%s" % binary_to_hex(ekeyID))
      ekeyObj.lock()

   #############################################################################
   def lockwalletekeysall(self):
      for eid,ekeyObj in self.ekeyMap.iteritems():
         ekeyObj.lock()
      
      
   #############################################################################
   def checkWalletLockTimeout(self):
      currTime = RightNow()
      for eid,ekeyObj in self.ekeyMap.iteritems():
         if currTime > ekeyObj.relockAtTime:
            ekeyObj.lock()


   #############################################################################
   def createNewLinkedWallet(self, typeStr, withEncrypt,):


   #############################################################################
   def writeFreshWalletFile(self, path, newName='', newDescr=''):


   #############################################################################
   # 
   def CreateNewWalletFile(self, 
                           createNewRoot=True, \
                           securePassphrase=None, \
                           kdfTargSec=DEFAULT_COMPUTE_TIME_TARGET, \
                           kdfMaxMem=DEFAULT_MAXMEM_LIMIT, \
                           defaultInnerEncrypt=None, \
                           defaultOuterEncrypt=None, \
                           doRegisterWithBDM=True, \
                           ):
                             #newWalletFilePath=None, \
                             #plainRootKey=None, \
                             ##withEncrypt=True, securePassphrase=None, \
                             #kdfTargSec=DEFAULT_COMPUTE_TIME_TARGET, \
                             #kdfMaxMem=DEFAULT_MAXMEM_LIMIT, \
                             #shortLabel='', longLabel='', isActuallyNew=True, \
                             #doRegisterWithBDM=True):
      raise NotImplementedError
      """

      We skip the atomic file operations since we don't even have
      a wallet file yet to safely update.

      DO NOT CALL THIS FROM BDM METHOD.  IT MAY DEADLOCK.
      """

      
      if self.calledFromBDM:
         LOGERROR('Called createNewWallet() from BDM method!')
         LOGERROR('Don\'t do this!')
         return None

      LOGINFO('***Creating new deterministic wallet')

      #####
      # Create a new KDF -- we need one for just about every wallet, regardless
      # of whether we are using encryption (yet).  The new KDF will be stored
      # with the wallet, and used by default whenever we want to encrypt 
      # something
      LOGDEBUG('Creating new KDF object')
      newKDF = KdfObject().createNewKDF('ROMixOv2', kdfTargSec, kdfMaxMem)
      self.kdfMap[newKDF.getKdfID()] = newKDF

      #####
      # If a secure passphrase was supplied, create a new master encryption key
      LOGDEBUG('Creating new master encryption key')
      if not securePassphrase is None:
         securePassphrase = SecureBinaryData(securePassphrase)
         newEKey = EncryptionKey().createNewMasterKey(newKDF, \
                                                   'AE256CFB', \
                                                   securePassphrase)
         self.ekeyMap[newEKey.getEncryptionKeyID()] = newEKey

      #####
      # If requested (usually is), create new master seed and the first wlt
      LOGDEBUG('Creating new master root seed & node')
      if createNewRoot:
         newRoot = ArmoryRoot().CreateNewMasterRoot()
      



      # Create the root address object
      rootAddr = PyBtcAddress().createFromPlainKeyData( \
                                             plainRootKey, \
                                             IV16=IV, \
                                             willBeEncr=withEncrypt, \
                                             generateIVIfNecessary=True)
      rootAddr.markAsRootAddr(chaincode)

      # This does nothing if no encryption
      rootAddr.lock(self.kdfKey)
      rootAddr.unlock(self.kdfKey)

      firstAddr = rootAddr.extendAddressChain(self.kdfKey)
      first160  = firstAddr.getAddr160()

      # Update wallet object with the new data
      self.useEncryption = withEncrypt
      self.addrMap['ROOT'] = rootAddr
      self.addrMap[firstAddr.getAddr160()] = firstAddr
      self.uniqueIDBin = (ADDRBYTE + firstAddr.getAddr160()[:5])[::-1]
      self.uniqueIDB58 = binary_to_base58(self.uniqueIDBin)
      self.labelName  = shortLabel[:32]
      self.labelDescr  = longLabel[:256]
      self.lastComputedChainAddr160 = first160
      self.lastComputedChainIndex  = firstAddr.chainIndex
      self.highestUsedChainIndex   = firstAddr.chainIndex-1
      self.wltCreateDate = long(RightNow())
      self.linearAddr160List = [first160]
      self.chainIndexMap[firstAddr.chainIndex] = first160

      # We don't have to worry about atomic file operations when
      # creating the wallet: so we just do it naively here.
      self.walletPath = newWalletFilePath
      if not newWalletFilePath:
         shortName = self.labelName .replace(' ','_')
         # This was really only needed when we were putting name in filename
         #for c in ',?;:\'"?/\\=+-|[]{}<>':
            #shortName = shortName.replace(c,'_')
         newName = 'armory_%s_.wallet' % self.uniqueIDB58
         self.walletPath = os.path.join(ARMORY_HOME_DIR, newName)

      LOGINFO('   New wallet will be written to: %s', self.walletPath)
      newfile = open(self.walletPath, 'wb')
      fileData = BinaryPacker()

      # packHeader method writes KDF params and root address
      headerBytes = self.packHeader(fileData)

      # We make sure we have byte locations of the two addresses, to start
      self.addrMap[first160].walletByteLoc = headerBytes + 21

      fileData.put(BINARY_CHUNK, '\x00' + first160 + firstAddr.serialize())


      # Store the current localtime and blocknumber.  Block number is always 
      # accurate if available, but time may not be exactly right.  Whenever 
      # basing anything on time, please assume that it is up to one day off!
      time0,blk0 = getCurrTimeAndBlock() if isActuallyNew else (0,0)

      # Don't forget to sync the C++ wallet object
      self.cppWallet = Cpp.BtcWallet()
      self.cppWallet.addAddress_5_(rootAddr.getAddr160(), time0,blk0,time0,blk0)
      self.cppWallet.addAddress_5_(first160,              time0,blk0,time0,blk0)

      # We might be holding the wallet temporarily and not ready to register it
      if doRegisterWithBDM:
         TheBDM.registerWallet(self.cppWallet, isFresh=isActuallyNew) # new wallet


      newfile.write(fileData.getBinaryString())
      newfile.close()

      walletFileBackup = self.getWalletPath('backup')
      shutil.copy(self.walletPath, walletFileBackup)

      # Lock/unlock to make sure encrypted keys are computed and written to file
      if self.useEncryption:
         self.unlock(secureKdfOutput=self.kdfKey)

      # Let's fill the address pool while we are unlocked
      # It will get a lot more expensive if we do it on the next unlock
      if doRegisterWithBDM:
         self.fillAddressPool(self.addrPoolSize, isActuallyNew=isActuallyNew)

      if self.useEncryption:
         self.lock()


      SERIALIZEEVERYTHINGINTO THE FILE
      self.writeFreshWalletFile(filepath)
      return self



      



#############################################################################
class ArmoryAddress(WalletEntry):

   FILECODE = 'ADDR'

   def __init__(self):
      pass


PRIV_KEY_AVAIL = enum('None', 'Available', 'NeedDecrypt', 'NextUnlock')
AEKTYPE = enum('Uninitialized', 'BIP32', 'ARMORY135', 'JBOK')






################################################################################
class AddressLabel(WalletEntry):
  
   FILECODE = 'ALBL' 

   def __init__(self, scrAddrStr=None, label=None):
      self.scrAddr = scrAddrStr
      self.label   = toUnicode(lbl)

   def initialize(self, scrAddrStr=None, lbl=None):

   def serialize(self):
      if self.scrAddrStr is None:
         raise UninitializedError('AddrLabel not initialized')

      bp = BinaryPacker()
      bp.put(VAR_STR,     self.scrAddr)
      bp.put(VAR_UNICODE, self.label)
      return bp.getBinaryString()

   def unserialize(self, theStr):
      bu = makeBinaryUnpacker(theStr)
      scraddr = bu.get(VAR_STR)
      lbl     = bu.get(VAR_UNICODE)
      self.__init__(scraddr, lbl)
      return self


################################################################################
class TxLabel(WalletEntry):

   FILECODE = 'TLBL'

   #############################################################################
   def __init__(self, txidFull=None, txidMall=None, comment=None):
      """
      "Mall" refers to malleability-resistant.  This isn't just for 
      transactions that have been "mall"ed after broadcast, but for 
      offline and multi-sig transactions that haven't been signed yet,
      for which we don't have the full ID.  The user may set the comment
      when creating the tx, and we want Armory to later associate 
      that comment with the final transaction.  For each transaction
      in the ledger, we will look for both the "Full" and "Mall" version
      of the transaction ID (if available).  
      """
      self.setComment(txidFull, txidMall, comment)

   #############################################################################
   def setComment(self, txidFull, txidMall, comment):
      self.txidFull =   '' if txidFull is None else txidFull[:]
      self.txidMall =   '' if txidMall is None else txidMall[:]
      self.uComment  = u'' if comment  is None else toUnicode(comment)

   #############################################################################
   def serialize(self):
      if [len(self.txidFull), len(self.txidMall)] = [0,0]:
         raise UninitializedError('TxComm is not associated with any tx')

      bp = BinaryPacker()
      bp.put(VAR_STR,      self.txidFull)
      bp.put(VAR_STR,      self.txidMall)
      bp.put(VAR_UNICODE,  self.uComment)
      return bp.getBinaryString()

   #############################################################################
   def unserialize(self, theStr):
      bu = makeBinaryUnpacker(theStr)
      self.txidFull = bu.get(VAR_STR)
      self.txidMall = bu.get(VAR_STR)
      self.uComment = bu.get(VAR_UNICODE)
      return self


################################################################################
################################################################################
class ArmoryFileHeader(object):
  
   WALLETMAGIC = '\xffARMORY\xff'
   #############################################################################
   def __init__(self):
      # Note, we use a different fileID than wallet 1.35 so that older versions
      # of Armory don't attempt to load the 2.0 wallets
      LOGDEBUG('Creating file header')
      self.flags         = BitSet(32)
      self.createTime    = 0
      self.rsecParity    = RSEC_PARITY_BYTES
      self.rsecPerData   = RSEC_PER_DATA_BYTES
      self.isDisabled      = True


      # Identifies whether this file is intended to be used as a full wallet,
      # or perhaps holds metadata or transient data for some other operation
      self.isTransferWallet = False
      self.isSupplemental = False


   
   #############################################################################
   def initialize(self, *args):
      raise NotImplementedError

   #############################################################################
   def serializeHeaderData(self, headerSize=200):
      """
      We leave a lot of extra space in header for future expansion, since
      header data is always up front, it's always got to be the same size.
      """
      self.flags.reset()
      self.flags.setBit(0, self.isTransferWallet)
      self.flags.setBit(1, self.isSupplemental)
      
      hdata = BinaryPacker()
      hdata.put(BINARY_CHUNK,    ArmoryFileHeader.WALLETMAGIC, width=8)
      hdata.put(UINT32,          getVersionInt(ARMORY_WALLET_VERSION))
      hdata.put(BINARY_CHUNK,    MAGIC_BYTES,           width=4)
      hdata.put(BITSET,          self.flags,            width=4)
      hdata.put(UINT64,          self.createTime)      
      hdata.put(UINT32,          self.rsecParity
      hdata.put(UINT32,          self.rsecPerData)

      sizeRemaining = headerSize - hdata.getSize()
      hdata.put(BINARY_CHUNK,    '\x00'*sizeRemaining)


   #############################################################################
   def unserializeHeaderData(self, theStr):
      toUnpack = makeBinaryUnpacker(theStr)
      hdata = BinaryPacker()
      hdata.get(BINARY_CHUNK,    WALLETMAGIC,           width=  8)
      hdata.get(UINT32,          getVersionInt(ARMORY_WALLET_VERSION))
      hdata.get(BINARY_CHUNK,    MAGIC_BYTES,           width=  4)
      hdata.get(UINT32,          self.flags.toInteger())
      hdata.get(UINT64,          self.createTime)      
      return self
     
   

   #############################################################################
   def serialize(self):
      # Serialization of header data needs to be constant so it can always 
      # be overwritten in place.  All other data types are WalletEntry objs
      # which will be delete-append if overwritten with larger data.

      headerData = self.serializeHeaderData()

      

      # We avoid 
      rsecCode = createRSECCode(bp.getBinaryString())
      bp.put(UINT32,          len(rsecCode))
      bp.put(BINARY_CHUNK,    rsecCode,              width=64)
      return bp.getBinaryString()

   #############################################################################
   @staticmethod
   def Unserialize(theStr):
      afh = ArmoryFileHeader()

      toUnpack = makeBinaryUnpacker(theStr)

      headerData    = toUnpack.get(BINARY_CHUNK, 200)
      rsecParitySz  = toUnpack.get(UINT32)
      rsecPerData   = toUnpack.get(UINT32)
      rsecCodeSize  = toUnpack.get(UINT32)
      rsecCode      = toUnpack.get(BINARY_CHUNK, rsecCodeSize)
      zeros         = toUnpack.get(BINARY_CHUNK, 64-rsecCodeSize)
      if not zeros.count('\x00')==len(zeros):
         raise UnpackerError('Empty space/padding as non-zero bytes')

      rsecData,failFlag,modFlag = checkRSECCode(rsecData, rsecCode)

      hunpack = BinaryUnpacker(headerData)
      fileID      = hunpack.get(BINARY_CHUNK, 8)
      armoryVer   = hunpack.get(UINT32)
      magicbytes  = hunpack.get(BINARY_CHUNK, 4)
      flagsInt    = hunpack.get(UINT32)

      
      if not fileID==ArmoryFileHeader.WALLETMAGIC:
         if not fileID=='\xbaWALLET\x00':
            LOGERROR('The wallet file does not have the correct magic bytes')
            raise FileExistsError('This does not appear to be an Armory wallet')
         else:
            LOGERROR('You attempted to load an Armory 1.35 wallet!  Must use'
                     'Armory version 0.92 or ealier to do this, or use the '
                     'migration tool to convert it to the new format.')
            raise FileExistsError('Old Armory wallet, it must be migrated!')
         

      if not magicbytes==MAGIC_BYTES:
         LOGERROR('This wallet is for the wrong network!')
         LOGERROR('   Wallet is for:  %s ', BLOCKCHAINS[magicbytes])
         LOGERROR('   You are on:     %s ', BLOCKCHAINS[MAGIC_BYTES])
         raise NetworkIDError('Wallet is for wrong network!')

      if not armoryVer==getVersionInt(ARMORY_WALLET_VERSION):
         LOGWARN('This wallet is for an older version of Armory!')
         LOGWARN('Wallet version: %d', armoryVer)
         LOGWARN('Armory version: %d', getVersionInt(ARMORY_WALLET_VERSION))


      if [rsecParity, rsecPerData] != [RSEC_PARITY_BYTES, RSEC_PER_DATA_BYTES]:
         # Technically, we could make all wallet code accommodate dynamic
         # RSEC parameters, but it would add some complexity.  
         LOGERROR('This wallet uses different Reed-Solomon error correction'
                  'parameters than this version of Armory')
         afh.isDisabled = True
         return afh
      

      endByte = toUnpack.getPosition()
      rsecData = toUnpack.getBinaryString()[startByte:endByte]

      afh.initialize(flags)
      return afh



################################################################################
################################################################################
class ArmoryExtendedKey(WalletEntry):
   def __init__(self):
      self.isWatchOnly     = False
      self.pubHash160      = ''
      self.privCryptInfo   = ArmoryCryptInfo(None)
      self.sbdPrivKeyData  = NULLSBD()
      self.sbdPublicKey33  = NULLSBD()
      self.sbdChaincode    = NULLSBD()
      self.aekParent160    = ''
      self.aekRoot160      = ''
      self.derivePath      = []
      self.useCompressPub  = True
      self.aekType         = AEKTYPE.Uninitialized
      self.isUsed          = False
      self.keyBornTime     = 0
      self.keyBornBlock    = 0
      self.keyRAMLifetime  = 10
      self.relockAtTime    = 0

      self.aekChildMap     = {}
      self.aekScrAddrMap   = {}
      self.aekParent       = None
      self.aekRoot         = None
      self.masterEkeyRef   = None

   #############################################################################
   def getAEKCopy(self, newKeyData=None):
      """
      Note:  This copies just the base class AEK members.  It doesn't copy
             any members that are in the derived class, though the child class
             will be the same class as self 
      """
      childAddr = self.__class__()

      childAddr.isWatchOnly     = self.isWatchOnly
      childAddr.privCryptInfo   = self.privCryptInfo.copy()
      childAddr.aekParent160    = self.aekParent160
      childAddr.aekRoot160      = self.aekRoot160
      childAddr.derivePath      = self.derivePath
      childAddr.useCompressPub  = self.useCompressPub
      childAddr.aekType         = self.aekType
      childAddr.isUsed          = self.isUsed
      childAddr.keyBornTime     = self.keyBornTime
      childAddr.keyBornBlock    = self.keyBornBlock
      childAddr.keyRAMLifetime  = self.keyRAMLifetime
      childAddr.relockAtTime    = self.relockAtTime

      childAddr.aekChildMap     = self.aekChildMap
      childAddr.aekScrAddrMap   = self.aekScrAddrMap
      childAddr.aekParent       = self.aekParent
      childAddr.aekRoot         = self.aekRoot
      childAddr.masterEkeyRef   = self.masterEkeyRef

      if newKeyData is None:
         childAddr.sbdPrivKeyData  = self.sbdPrivKeyData.copy()
         childAddr.sbdPublicKey33  = self.sbdPublicKey33.copy()
         childAddr.sbdChaincode    = self.sbdChaincode.copy()
         childAddr.pubHash160      = self.pubHash160
      else:
         childAddr.sbdPrivKeyData  = NULLSBD()
         childAddr.sbdPublicKey33  = newKeyData['PubKey'].copy()
         childAddr.sbdChaincode    = newKeyData['Chaincode'].copy()
         childAddr.scrAddrStr      = childAddr.generateScrAddr()
         plainPriv = newKeyData['PlainPriv']

         # If there's no encryption, the .encrypt call will use IDENTITY
         if newKeyData['PlainPriv'].getSize() > 0:
            childAddr.sbdPrivKeyData = self.privCryptInfo.encrypt( \
                                 newKeyData['PlainPriv'], self.masterEkeyRef)

      return childAddr


   #############################################################################
   def addChildRef(self, childAEK):
      NotImplementedError('This needs to be reimplemented by derived class!')

   #############################################################################
   def initFromEncryptedPrivData(self, 
                        sbdPrivCrypt=None, sbdPub=None, sbdChain=None,    
                        privCryptInfo=None, parentID=None, parentRef=None,
                        keyBorn=0, derivePath=None, wltRef=None):
      

      plainPriv=NULLSBD()

      try:
         if privCryptInfo is None or privCryptInfo.noEncryption():
            plainPriv = sbdPriv.copy()
         else:
            self.privCryptInfo = privCryptInfo.copy()
         
         if sbdPriv and not sbdPub:
            sbdPub = CryptoECDSA().ComputePublicKey(sbdPriv)

         self.pubHash160 = sbdPub.getHash160()
      
      finally:
         plainPriv.destroy()


   #############################################################################
   def initFromPlainPrivData(self, 

   #############################################################################
   def initFromPlainPrivDataToBeEncrypted(self, 


   #############################################################################
   def initializeAEK(self, privData=None, alreadyCryptInfo=None,
                              toBeEncrID=None, pub=None, chain=None, parRef=None, 
                              derivePath=None, wltRef=None, **classSpecificArgs):

      if privData is None:
         aek.createFromPublicKeyData(pub, chain, parRef, derivePath, wltRef)
      else:
         if alreadyCryptInfo is None:
            if toBeEncrID is None:
               aek.createFromPlainKeyData(privData, pub, chain
                
         elif isinstance(alreadyCryptInfo, ArmoryCryptInfo):
            aek.createFromEncryptedKeyData
            aci = ArmoryCryptInfo(NULLKDF, 'AES256CBC', toBeEncrID, 'PUBKEY20')
      
      if getattr(aek, 'initialize'):
         aek.initialize(**classSpecificArgs)  # defined in the derived AEK class

      return aek
   
      
   #############################################################################
   def serialize(self):

      pubKey = self.sbdPublicKey33.copy()
      if self.sbdPublicKey33.getSize() == 65:
         pubKey = CryptoECDSA().CompressPoint(self.sbdPublicKey33)

      parentID = self.aekParent.getID() if self.aekParent else ''
      rootID   = self.aekRoot.getID()   if self.aekRoot   else ''

      flags = BitSet(16)
      flags.setBit(0, self.isWatchOnly)
      flags.setBit(1, self.useCompressPub)
      flags.setBit(2, self.privKeyNextUnlock)
      flags.setBit(3, self.sbdPrivKeyData.getSize()==0)
      flags.setBit(4, self.sbdChaincode.getSize()==0)


      # We are not committed to fixed-width wallet entries.  Might as well
      # Save space if fields are empty by using VAR_STRs
      bp = BinaryPacker()
      bp.put(UINT32,        getVersionInt(ARMORY_WALLET_VERSION))
      bp.put(BINARY_CHUNK,  self.EXTKEYTYPE,                 8)
      bp.put(BITSET,        flags,                           2)
      bp.put(UINT64,        self.keyBornTime)
      bp.put(UINT32,        self.keyBornBlock)
      bp.put(BINARY_CHUNK,  self.privCryptInfo.serialize(), 32)
      bp.put(VAR_STR,       self.sbdPrivKeyData.toBinStr())
      bp.put(VAR_STR,       pubKey)
      bp.put(VAR_STR,       self.sbdChaincode.toBinStr())
      bp.put(VAR_STR,       parentID)
      bp.put(VAR_STR,       rootID)
      bp.put(UINT16,        len(self.derivePath))
      for idx in self.derivePath:
         bp.put(UINT32, idx)
      
      # Add Reed-Solomon error correction 
      allDataSoFar = bp.getBinaryString()
      bp.put(VAR_STR,       createRSECCode(allDataSoFar))
      return bp.getBinaryString()

      
   #############################################################################
   def unserialize(self, toUnpack, wltRef=None):
      # Does nothing if it's already a binary packer, and leaves its state
      # at the end of the serialized AEK.  If not a BinaryPacker, creates one
      # just for reading, and its end state is irrelevant.
      toUnpack = makeBinaryUnpacker(toUnpack)

      version = toUnpack.get(UINT32) 
      if version != getVersionInt(ARMORY_WALLET_VERSION):
         LOGWARN('AEK version in file: %s,  Armory Wallet version: %s', 
                     getVersionString(readVersionInt(version)), 
                     getVersionString(ARMORY_WALLET_VERSION))
         

      startPos = toUnpack.getPosition()

      # We are not committed to fixed-width wallet entries.  Might as well
      # Save space if fields are empty by using VAR_STRs
      self.EXTKEYTYPE     = toUnpack.get(BINARY_CHUNK, 8)
      flags               = toUnpack.get(BITSET,       2)
      self.keyBornTime    = toUnpack.get(UINT64)
      self.keyBornBlock   = toUnpack.get(UINT32)
      privCryptInfoSer    = toUnpack.get(BINARY_CHUNK, 32)
      privk               = toUnpack.get(VAR_STR)
      pubk                = toUnpack.get(VAR_STR)
      chain               = toUnpack.get(VAR_STR)
      parentID            = toUnpack.get(VAR_STR)
      rootID              = toUnpack.get(VAR_STR)
      pathSize            = toUnpack.get(UINT16)
      self.derivePath = []
      for idx in range(pathSize):
         self.derivePath.append(toUnpack.get(UINT32))

      rsecCheck           = toUnpack.get(VAR_STR)
      
      currKeyPosition     = toUnpack.getPosition()
      rsecProtectedData   = toUnpack.getBinaryString()[startPos:currPos]
      serKeyData,failFlag,modFlag = checkRSECCode(rsecProtectedData, rsecCode)
      if failFlag:
         LOGERROR('Unrecoverable error in wallet entry')
         we.isUnrecoverable = True 
         return we
      elif modFlag:
         LOGWARN('Error in wallet file corrected successfully')
         we.needRewrite = True 
      
      self.isWatchOnly       = flags.getBit(0)
      self.useCompressPub    = flags.getBit(1)
      self.privKeyNextUnlock = flags.getBit(2)
      emptyPriv              = flags.getBit(3)
      emptyChain             = flags.getBit(4)

      self.sbdPrivKeyData = NULLSBD() if emptyPriv  else SecureBinaryData(privk)
      self.sbdChaincode   = NULLSBD() if emptyChain else SecureBinaryData(chain)

      privk = None
      chain = None
      
      return self
      


   #############################################################################
   def getPrivKeyAvailability(self):
      if self.isWatchOnly:
         return PRIV_KEY_AVAIL.None
      elif self.sbdPrivKeyData.getSize() > 0:
         if self.privCryptInfo.useEncryption():
            return PRIV_KEY_AVAIL.Available
         else:
            return PRIV_KEY_AVAIL.NeedDecrypt
      elif self.privKeyNextUnlock:
         return PRIV_KEY_AVAIL.NextUnlock
      else:
         raise ShouldNotGetHereError('AEK that is not WO, but no key info?')


   #############################################################################
   def useEncryption(self):
      return self.privCryptInfo.useEncryption()



   #############################################################################
   def getSerializedPubKey(self, serType='hex'):
      """
      The various public key serializations:  "hex", "xpub"
      """
      if not self.useCompressPub:
         pub = CryptoECDSA().UncompressPoint(self.sbdPublicKey33).copy()
      else:
         pub = self.sbdPublicKey33.copy()
         
      if serType.lower()=='hex':
         return pub.toHexStr()

      elif serType.lower()=='xpub':
         raise NotImplementedError('Encoding not implemented yet')

         
   #############################################################################
   def getSerializedPrivKey(self, serType='hex'):
      """
      The various private key serializations: "hex", "sipa", "xprv"
      """

      if self.useEncryption() and self.isLocked():
         raise WalletLockError('Cannot serialize locked priv key')

      lastByte = '\x01' if self.useCompressPub else ''
      binPriv = self.getPlainPrivKeyCopy().toBinStr() + lastByte
         
      if serType.lower()=='hex':
         return binary_to_hex(hexPriv)
      elif serType.lower()=='sipa':
         binSipa '\x80' + binPriv + computeChecksum('\x80' + binPriv)
         return binary_to_hex(binSipa)
      elif serType.lower()=='xprv':
         raise NotImplementedError('xprv encoding not yet implemented')


   #############################################################################
   def getPrivCryptArgs(self, cryptInfoObj=None):
      """
      Examines self.privCryptInfo and produces as many arguments as it can
      that are needed to call self.privCryptInfo.encrypt/decrypt.
      """
      if cryptInfoObj is None:
         cryptInfoObj = self.privCryptInfo

      mapOut = {}
      if self.cryptInfoObj.noEncryption():
         return mapOut

      if self.cryptInfoObj.getEncryptIVSrc[0] == CRYPT_IV_SRC.PUBKEY20:
         mapOut['ivData'] = self.sbdPublicKey33.getHash256()[:16]
      else:
         # If the IV is stored we don't need to pass it through, it
         # will grab it from itself when cryptInfoObj.decrypt/encrypt 
         # is called
         mapOut['ivData']  = None

      mapOut['isLocked'] = False
      if self.wltFileRef is None:
         mapOut['ekeyObj']  = None
         mapOut['kdfObj']   = None
      else:
         kid = self.cryptInfoObj.kdfObjID
         eid = self.cryptInfoObj.keySource
         mapOut['kdfObj']   = self.wltFileRef.kdfMap.get(kid)
         mapOut['ekeyObj']  = self.wltFileRef.ekeyMap.get(eid)
         if not mapOut['ekeyObj'] is None:
            mapOut['isLocked'] = mapOut['ekeyObj'].isLocked()

      return mapOut
      

   #############################################################################
   @VerifyArgTypes(keyData=[SecureBinaryData,None])
   def getPlainPrivKeyCopy(self, keyData=None, kdfObj=None, ekeyObj=None):
      """
      This is the only way to get the private key out of an AEK object.
      The plain key is never kept in an AEK object, which is why there's
      no lock() and unlock() methods for AEK.  Instead, we only ever lock
      and unlock the master encryption key, which is either supplied as
      and argument to this function, or fetched from the parent wallet file.

      In general, the extra input args are not going to be used in the 
      app.  The ekeyObj will always be unlocked before we get here, and
      the getPrivCryptArgs() call will fetch it for us from the wallet file.  
      We might need to use the extra args if this object is not in a wallet
      file and/or we are creating utility scripts using these objects.

      NOTE:  This returns an SBD object which needs to be .destroy()ed by
             the caller when it is finished with it.
      """

      if self.isWatchOnly:
         raise KeyDataError('Cannot get priv key from watch-only wallet')

      if self.privCryptInfo.noEncryption():
         return self.sbdPrivKeyData.copy()

      aciDecryptAgs = self.getPrivCryptArgs(self.privCryptInfo)

      # Override any args returned above with non-empty args to this func
      if not kdfObj is None:
         aciDecryptAgs['kdfObj'] = kdfObj
      if not ekeyObj is None:
         aciDecryptAgs['ekeyObj'] = ekeyObj


      ##########################################################################
      if self.privKeyNextUnlock:
         self.resolveNextUnlockFlag()

      try:
         return self.privCryptInfo.decrypt( \
                           self.sbdPrivKeyData, keyData, **aciDecryptAgs)
      except:
         LOGEXCEPT('Failed to decrypt private key')
         return NULLSBD()


      
   #############################################################################
   def resolveNextUnlockFlag(self):
      """
      Any time the master key is unlocked, use this to fill in the private
      keys for all nodes from root to here, marked privKeyAvail ~ NextUnlock
      """
      if self.parentAEK.privKeyNextUnlock:
         self.parentAEK.resolveNextUnlockFlag()

      try:
         newPriv = NULLSBD()
         regenThisAEK = self.parentAEK.spawnChild(self.derivePath[-1], 
                                                  privSpawnReqd=True)
         aciCryptArgs = self.getPrivCryptArgs()
         newPriv = regenThisAEK.getPlainPrivKeyCopy()
         self.sbdPrivKeyData = self.privCryptInfo.encrypt(newPriv, **aciCryptArgs)
         self.privKeyNextUnlock = False
         self.fsync()
      finally:
         newPriv.destroy()

      
   #############################################################################
   def __signData(self, dataToSign, deterministicSig=False, normSig='Dontcare'):
      """
      This returns the raw data, signed using the CryptoECDSA module.  This 
      should probably not be called directly by a top-level script, but 
      instead the backbone of a bunch of standard methods for signing 
      transactions, messages, perhaps Proof-of-Reserve trees, etc.

      "normSig" is based on a proposal to only allow even s-values, or 
      odd s-values to limit transaction malleability.  We might as well
      put it here, though the default is not to mess with the outpout
      of the SignData call.
      """
      if self.useEncryption() and self.isLocked():
         raise WalletLockError('Cannot sign with locked priv key')
      
      try:
         self.unlock()

         if deterministicSig:
            raise NotImplementedError('Cannot do deterministic signing yet')
            sig = CryptoECDSA().SignData_RFC6979(dataToSign, self.sbdPrivKeyPlain)
         else:
            sig = CryptoECDSA().SignData(dataToSign, self.binPrivKey32_Plain)

         sigstr = sig.toBinStr()

         rBin = sigstr[:32 ]
         sBin = sigstr[ 32:]

         if not normSig=='Dontcare':
            # normSig will either be 'even' or 'odd'.  If the calculated
            # s-value does not match, then use -s mod N which will be 
            # correct
            raise NotImplementedError('This code is not yet tested!')
            sInt = binary_to_int(sBin, BIGENDIAN)
            if (normSig=='even' and sInt%2==1) or \
               (normSig=='odd'  and sInt%2==0):
               sInt = (-sInt) % SECP256K1_MOD
               
            sBin = int_to_binary(sInt, widthBytes=32, endOut=BIGENDIAN)

         return (rBin, sBin)

      except:
         LOGEXCEPT('Error generating signature')
      finally:
         self.sbdPrivKeyPlain.destroy()
      

   #############################################################################
   def signTransaction(self, serializedTx, deterministicSig=False):
      rBin,sBin = self.__signData(serializedTx, deterministicSig)
      return createSigScriptFromRS(rBin, sBin)

      
   #############################################################################
   def signMessage(self, msg, deterministicSig=False):
      """
      Returns just raw (r,s) pair instead of a sigscript because this is 
      raw message signing, not transaction signing.  We match Bitcoin-Qt
      behavior which is to prefix the message with "Bitcoin Signed Message:" 
      in order to guarantee that someone cannot be tricked into signing
      a real transaction:  instead of signing the input, MSG, it will only 
      sign hash("Bitcoin Signed Message:\n" + MSG) which cannot be a
      transaction
      """
      raise NotImplementedError('Currently this function is not tested')
      msgPrefix = 'Bitcoin Signed Message:\n'
      bp = BinaryPacker()
      bp.put(VAR_INT,  len(msgPrefix))
      bp.put(BINARY_CHUNK, msgPrefix)
      bp.put(VAR_INT,  len(msg))
      bp.put(BINARY_CHUNK, msg)
      msgToSign = hash256(bp.getBinaryString())
      return self.__signData(msgToSign, deterministicSig)




################################################################################
################################################################################
class Armory135ExtendedKey(ArmoryExtendedKey):

   EXTKEYTYPE = 'ARMRY135'

   #############################################################################
   def __init__(self, *args, **kwargs):
      super(Armory135ExtendedKey, self).__init__(*args, **kwargs)
      self.useCompressPub = False
      self.chainIndex = None
      self.derivePath = [0]


   #############################################################################
   def getExtendedKeyByScrAddr(self, pathList, privSpawnReqd=False):
      raise NotImplementedError('This method not avail for A135 wallet chains')

   #############################################################################
   def getExtendedKeyByChainIndex(self, pathList, privSpawnReqd=False):
      raise NotImplementedError('This method not avail for A135 wallet chains')

   #############################################################################
   def getAddrObjByPath(self, pathList, privSpawnReqd=False):
      raise NotImplementedError('This method not avail for A135 wallet chains')


   #############################################################################
   def addChildRef(self, childAEK):
      # For Armory135 addrs, we store the child in both aekParent AND aekRoot
      self.aekChildMap[0] = childAEK
      self.aekRoot.aekChildMap[self.chainIndex] = childAEK
      self.aekRoot.aekScrAddrMap[childAEK.getScrAddr()] = childAEK


   #############################################################################
   def calculateNextUnlockKeysIfNeeded(self):
      if not self.privKeyNextUnlock:
         return

      if self.aekParent is None:
         raise KeyDataError('No parent defined from which to derive this key')

      if self.childID is None:
         raise KeyDataError('No derivation path defined to derive this key')

      # Originally used an elegant recursive call here, but was worried 
      # about that corner case where someone has 100k addrs and will hit 
      # the recursion limit... 

      # Accum refs back to first key whose parent.privKeyNextUnlock==False
      aekStack = [self]
      while aekStack[-1].aekParent.privKeyNextUnlock:
         aekStack.append(aekStack[-1].aekParent)
      
      # Now walk backwards, deriving every child from its parent
      for aek in aekStack[::-1]:
         # This is technically still recursive, but we've guaranteed it will
         # only recurse once (because the parent.privKeyNextUnlock == False)
         newAek = aek.aekParent.spawnChild(self.derivePath[-1], True)
            
         if aek.sbdPublicKey33.toBinStr()!=newAek.sbdPublicKey33.toBinStr():
            raise KeyDataError('Derived key supposed to match but does not')
      
         aek.sbdPrivKeyData    = newAek.sbdPrivKeyData.copy()
         aek.privKeyNextUnlock = False
                              

   #############################################################################
   @TimeThisFunction('SpawnChild135')
   def spawnChild(self, childID=0, privSpawnReqd=False):
      """
      We require some fairly complicated logic here, due to the fact that a
      user with a full, private-key-bearing wallet, may try to generate a new
      key/address without supplying a passphrase.  If this happens, the wallet
      logic gets mucked up -- we don't want to reject the request to
      generate a new address, but we can't compute the private key until the
      next time the user unlocks their wallet.  Thus, we have to save off the
      data they will need to create the key, to be applied on next unlock.
      """

      if not childID == 0:
         raise KeyDataError('Can only derive child ID=0 for 1.35 AEKs')


      # If the child key corresponds to a "hardened" derivation, we require
      # the priv keys to be available, or sometimes we explicitly request it
      if privSpawnReqd:
         pavail = self.getPrivKeyAvailability()
         if self.isWatchOnly or pavail==PRIV_KEY_AVAIL.None:
            raise KeyDataError('Requires priv key, but this is a WO ext key')

         if self.getPrivKeyAvailability()==PRIV_KEY_AVAIL.NeedDecrypt and 
            raise KeyDataError('Requires priv key, no way to decrypt it')

         if pavail==PRIV_KEY_AVAIL.NextUnlock:
            self.calculateNextUnlockKeysIfNeeded()
         


      pubKey65 = CryptoECDSA().UncompressPoint(self.sbdPublicKey33)
      logMult1 = NULLSBD()
      logMult2 = NULLSBD()
      sbdNewKey1 = NULLSBD()
      sbdNewKey2 = NULLSBD()
      sbdNewKey3 = NULLSBD()


      try:
         ecdsaObj = CryptoECDSA()
         if self.getPrivKeyAvailability()==PRIV_KEY_AVAIL.Available:
            privPlain = self.getPlainPrivKeyCopy()
            if privPlain.getSize()==0:
               raise KeyDataError('Private key not available for spawning')
            extendFunc = ecdsaObj.ComputeChainedPrivateKey
            extendArgs = [privPlain, self.sbdChaincode, pubKey65, logMult1]
            extendType = 'Private'
         elif self.getPrivKeyAvailability()==PRIV_KEY_AVAIL.None
            extendFunc = ecdsaObj.ComputeChainedPublicKey
            extendArgs = [pubKey65, self.sbdChaincode, logMult1]
            extendType = 'Public'
         
   
         # Do key extension twice
         sbdNewKey1 = extendFunc(*extendArgs)
         sbdNewKey2 = extendFunc(*extendArgs)

         if sbdNewKey1.toBinStr() == sbdNewKey2.toBinStr():
            sbdNewKey2.destroy()
            with open(MULT_LOG_FILE,'a') as f:
               f.write('%s chain (pkh, mult): %s,%s\n' % (extendType, logMult1.toHexStr()))
         else:
            LOGCRIT('Chaining failed!  Computed keys are different!')
            LOGCRIT('Recomputing chained key 3 times; bail if they do not match')
            sbdNewKey1.destroy()
            sbdNewKey2.destroy()
            logMult3 = SecureBinaryData()

            sbdNewKey1 = extendFunc(*extendArgs)
            sbdNewKey2 = extendFunc(*extendArgs)
            sbdNewKey3 = extendFunc(*extendArgs)
            LOGCRIT('   Multiplier1: ' + logMult1.toHexStr())
            LOGCRIT('   Multiplier2: ' + logMult2.toHexStr())
            LOGCRIT('   Multiplier3: ' + logMult3.toHexStr())

            if sbdNewKey1==sbdNewKey2 and sbdNewKey1==sbdNewKey3:
               sbdNewKey2.destroy()
               sbdNewKey3.destroy()
               with open(MULT_LOG_FILE,'a') as f:
                  f.write('Computed chain (pkh, mult): %s,%s\n' % (a160hex,logMult1.toHexStr()))
            else:
               sbdNewKey1.destroy()
               sbdNewKey2.destroy()
               sbdNewKey3.destroy()
               raise KeyDataError('Chaining %s Key Failed!' % extendType)
      finally:
         privPlain.destroy()
         sbdNewKey1.destroy()
         sbdNewKey2.destroy()
         sbdNewKey3.destroy()

      newAEK = {}
      if extendType=='Private':
         newAEK['PlainPriv']  = sbdNewKey1.copy()
         newAEK['PublicKey']   = CryptoECDSA().ComputePublicKey(sbdNewPriv)
         newAEK['Chaincode'] = self.sbdChaincode.copy()
      else:
         newAEK['PlainPriv']  = NULLSBD()
         newAEK['PublicKey']   = sbdNewKey1.copy()
         newAEK['Chaincode'] = self.sbdChaincode.copy()


      childAddr = self.copy()
      childAddr = self.getAEKCopy(self, newKeyData=newAEK):
      childAddr.chainIndex = self.chainIndex + 1
      childAddr.derivePath = [0]
      self.addChildRef(childAddr)
      return childAddr


         

   #############################################################################
   def createChildKeyFromKeyData(self, sbdPlainPriv, sbdPub, sbdChain):
      childAddr = self.copy()
      childAddr 
                                       privKey=sbdNewPriv, 
                                       pubKey=sbdNewPub, 
                                       chain=sbdNewChain)
      
      if extendType=='Private':
         
                                        
      childAddr.chainIndex     = self.chainIndex + 1
      childAddr.aekParent      = self
      childAddr.aekParent160   = self.getExtKeyID()
      childAddr.aekRoot160     = self.aekRoot160
      childAddr.privCryptInfo  = self.privCryptInfo
      childAddr.isInitialized  = True

      return childAddr



################################################################################
################################################################################
class ArmoryBip32ExtendedKey(ArmoryExtendedKey):

   EXTKEYTYPE = 'ARMBIP32'
   def __init__(self, *args, **kwargs):
      super(ArmoryBip32ExtendedKey, self).__init__(*args, **kwargs)


   #############################################################################
   def addChildRef(self, childAEK):
      if len(childAEK.derivePath) == 0:
         raise ValueError('Child AEK has no derive path')
         
      idx = childAEK.derivePath[-1]
      self.aekChildMap[idx] = childAEK

   #############################################################################
   def spawnChild(self, childID, privSpawnReqd=False):
      """
      Derive a child extended key from this one. 
      """

      TimerStart('spawnChild')
      startedLocked = False

      # If the child key corresponds to a "hardened" derivation, we require
      # the priv keys to be available, or sometimes we explicitly request it
      privSpawnReqd = privSpawnReqd or (childID & 0x80000000 > 0)
      if privSpawnReqd:
         if self.isWatchOnly:
            raise KeyDataError('Requires priv key, but this is a WO ext key')

         ekeyObj = self.getEkeyFromWallet(self.privCryptInfo.keySource)
         if ekeyObj is None:
            raise KeyDataError('Requires priv key but master key is not avail')

         if ekey.isLocked():
            raise WalletLockError('Must unlock private key to do priv spawn')
         

      # If we need the private key but it hasn't been calc yet, do it (recurse) 
      if privSpawnReqd and self.privKeyNextUnlock:
         if self.aekParent is None:
            raise KeyDataError('No parent defined from which to derive this key')

         if self.derivePath is None:
            raise KeyDataError('No derivation path defined to derive this key')

         # Recurse up the derivation path to derive the parent(s)
         if self.aekType == AEKTYPE.BIP32:
            if self.derivePath is None:
               raise KeyDataError('No derivation path defined to derive this key')
            aek = self.aekParent.spawnChild(self.derivePath[-1])
            
         if not aek.sbdPublicKey33.toBinStr() == self.sbdPublicKey33.toBinStr():
            raise keyData('Derived key supposed to match this one but does not')
   
         self.sbdPrivKeyData = aek.sbdPrivKeyData.copy()
                              
      # If the key is currently encrypted, going to need to unlock it
      if self.getPrivKeyAvailability()==PRIV_KEY_AVAIL.NeedDecrypt:
         unlockSuccess = self.unlock(ekeyObj, keyData)
         if not unlockSuccess:
            raise PassphraseError('Incorrect decryption data to spawn child')


         
      childAddr.childIdentifier
      extChild  = HDWalletCrypto().ChildKeyDeriv(self.getExtendedKey(), childID)

      # In all cases we compute a new public key and chaincode
      childAddr.binPubKey33  = extChild.getPub().copy()
      childAddr.binChaincode = extChild.getChain().copy()

      if privAvail==PRIV_KEY_AVAIL.Available:
         # We are extending a chain using private key data (unencrypted)
         childAddr.binPrivKey32_Plain  = extChild.getPriv().copy()
         childAddr.needToDerivePrivKey = False
      elif privAvail==PRIV_KEY_AVAIL.NextUnlock:
         # Copy the parent's encrypted key data to child, set flag
         childAddr.binPrivKey32_Encr = self.binPrivKey32_Encr.copy()
         childAddr.binChaincode      = self.binChaincode.copy()
         childAddr.needToDerivePrivKey = True
      elif privAvail==PRIV_KEY_AVAIL.None:
         # Probably just extending a public key
         childAddr.binPrivKey32_Plain  = SecureBinaryData(0)
         childAddr.needToDerivePrivKey = False
      else:
         LOGERROR('How did we get here?  spawnchild:')
         LOGERROR('   privAvail == %s', privAvail)
         LOGERROR('   encrypt   == %s', self.useEncryption)
         LOGERROR('Bailing without spawning child')
         raise KeyDataError
   
      childAddr.parentHash160      = self.getHash160()
      childAddr.binAddr160         = self.binPubKey33or65.getHash160()
      childAddr.useEncryption      = self.useEncryption
      childAddr.isInitialized      = True
      childAddr.childIdentifier    = childID
      childAddr.hdwDepth           = self.hdwDepth+1
      childAddr.indexList          = self.indexList[:]
      childAddr.indexList.append(childID)


      return ArmoryExtendedKey(
      return childAddr



   #############################################################################
   def getAddrLocatorString(self, locatorType='Plain', baseID=None):
      """
      This is a string that can be bundled with offline/multisig transactions
      to help lite devices identify that addresses/keys belong to them.  It's 
      basically just a wallet ID and path string.
   
      Can change the baseID to make the addr locator based on a different 
      root, perhaps the depth=1 node instead depth=0 
      """

      if not locatorType=='Plain':
         raise NotImplementedError('Cannot handle anything other than plain') 

      if baseID is None:
         baseID = self.aekRoot.getHash160()

      # Walk up the parent chain looking for the baseID, to make sure we
      # are only adding deriv-paths up to that BIP32 node
      aek   = self
      aekID = self.getHash160()
      derivePath = []
      while not aekID==baseID:
         if aek.aekParent is None:
            raise WalletAddressError('Did not find specified base ID')

         derivePath.append(aek.derivePath[-1])
         aek   = aek.aekParent
         aekID = aek.aekParent.getHash160()
   

      bp = BinaryPacker()
      bp.put(BINARY_CHUNK, baseID)
      bp.put(VAR_INT, len(derivePath))
      for i in derivePath[::-1]:
         bp.put(UINT32, i)
      return bp.getBinaryString() 
      

      



################################################################################
################################################################################
class ArmoryImportedKey(ArmoryExtendedKey):

   EXTKEYTYPE = 'IMPORTED'

   #############################################################################
   def getAddrLocatorString(self):
      return ''

   #############################################################################
   def addChildRef(self, childAEK):
      newIdx = len(self.aekChildMap)
      self.aekChildMap[newIdx] = childAEK

# Root modes represent how we anticipate using this root.  An Armory root
# marked as BIP32_Root means it is the top of a BIP32 tree generated from a 
# seed value.  If it is marked as BIP32_Floating, it means it is a branch 
# of BIP32 tree for which we don't have the rootroot (maybe it's a piece 
# of a BIP32 tree belonging to someone else given to us to generate payment 
# addresses, or for a multisig wallet).  ARM135 is the old Armory wallet 
# algorithm that was used for the first 3 years of Armory's existence.  
# JBOK stands for "Just a bunch of keys" (like RAID-JBOD).  JBOK mode will
# most likely only be used for imported keys and old Bitcoin Core wallets.
#ROOTTYPE = enum('UNINIT','ARM135', 'ARMORY20', 'JBOK', 'TREZV1', 'BTCHPV1')


#############################################################################
class ArmoryRoot(ArmoryExtendedKey):
   """
   A "wallet" will always have a root-root, which also will never be used
   for handling money (even though it technically has a private key).
   """
      
   FILECODE = 'ROOT'

   def __init__(self):
      super(ArmoryRoot, self).__init__()

      # General properties of this root object
      self.createDate  = 0
      self.labelName   = ''
      self.labelDescr  = ''

      # Each root is a candidate for being displayed to the user, should 
      # have a Base58 ID
      self.uniqueIDBin = ''
      self.uniqueIDB58 = ''    # Base58 version of reversed-uniqueIDBin

      # Track the children of this node, and the highest used
      self.childMap  = {}   # map of child pubHash160s to addrObjs
      self.childList = []   # list of addrObjs indexed by child index
      self.highestUsedChild = -1

      # If this root is intended to be used in multi-sig, it should be flagged.
      # In some cases this root will be created with the intention to become
      # part of a multisig wallet.  In that case, multisig flag will be on,
      # but the relationshipID will be zeros.  Once a relationship is defined
      # and added to the wallet, this structure will be updated.
      self.isForMultisig   = False
      self.relationshipID  = NULLSTR(20)

      # If this is a "normal" wallet, it is BIP32.  Other types of wallets 
      # (perhaps old Armory chains, will use different name to identify we
      # may do something different)
      #ROOTTYPE = enum('UNINIT','ARM135', 'ARMORY20', 'JBOK', 'TREZV1', 'BTCHPV1')
      self.rootType = ROOTTYPE.UNINIT

      # Extra data that needs to be encrypted
      self.seedCryptInfo   = ArmoryCryptInfo(None)
      self.seedNumBytes    = 0
      self.sbdSeedCrypt    = SecureBinaryData(0)


      # This is a root of a single-sig phone wallet.  We have the priv keys
      # here, but we don't intend to spend it from here.  Instead of a "Send"
      # button it should have a "Help I lost my phone!" button to sweep the
      # funds.
      self.isPhoneRoot   = False  

      # This root has no key data.  Mainly for JBOK
      self.isFakeRoot    = False  

      # Observer root of a multi-sig wlt, don't use
      self.isSiblingRoot = False  

      # Only use to gen deposit addrs, bal is meaningless.  This might be used
      # in the case that we integrate an exchange API, and we want Armory to 
      # be able to generate customer-specific deposit addresses (from floating
      # BIP32 branch).   The exchange may move the money around internally,
      # so the "balance" of this branch is meaningless, and "balance" should be
      # an API call to get your account balance.
      self.isDepositOnly = False  

      # In the event that some data type identifies this root as its parent AND
      # it identifies itself as critical AND we don't recognize it (such as if
      # you use a colored-coin variant of Armory and then later import the wlt
      # using vanilla Armory), this wallet should be identified as existent 
      # but unusable/disabled, to avoid doing something you shouldn't
      self.isDisabled = False

      # If the user decided to "remove" this wallet, then we simply mark it as
      # "removed" and don't display it or do anything with it.
      self.userRemoved = False

      


      """ # Old pybtcwallet stuff
      self.fileTypeStr    = '\xbaWALLET\x00'
      self.magicBytes     = MAGIC_BYTES
      self.version        = ARMORY_WALLET_VERSION  # (Major, Minor, Minor++, even-more-minor)
      self.eofByte        = 0
      self.cppWallet      = None   # Mirror of PyBtcWallet in C++ object
      self.cppInfo        = {}     # Extra info about each address to help sync
      self.watchingOnly   = False
      self.wltCreateDate  = 0

      # Three dictionaries hold all data
      self.addrMap     = {}  # maps 20-byte addresses to PyBtcAddress objects
      self.commentsMap = {}  # maps 20-byte addresses to user-created comments
      self.commentLocs = {}  # map comment keys to wallet file locations
      self.labelName   = ''
      self.labelDescr  = ''
      self.linearAddr160List = []
      self.chainIndexMap = {}
      if USE_TESTNET:
         self.addrPoolSize = 10  # this makes debugging so much easier!
      else:
         self.addrPoolSize = CLI_OPTIONS.keypool

      # For file sync features
      self.walletPath = ''
      self.doBlockchainSync = BLOCKCHAIN_READONLY
      self.lastSyncBlockNum = 0

      # Private key encryption details
      self.useEncryption  = False
      self.kdf            = None
      self.crypto         = None
      self.kdfKey         = None
      self.defaultKeyLifetime = 10    # seconds after unlock, that key is discarded
      self.lockWalletAtTime   = 0    # seconds after unlock, that key is discarded
      self.isLocked       = False
      self.testedComputeTime=None

      # Deterministic wallet, need a root key.  Though we can still import keys.
      # The unique ID contains the network byte (id[-1]) but is not intended to
      # resemble the address of the root key
      self.uniqueIDBin = ''
      self.uniqueIDB58 = ''   # Base58 version of reversed-uniqueIDBin
      self.lastComputedChainAddr160  = ''
      self.lastComputedChainIndex = 0
      self.highestUsedChainIndex  = 0 

      # All PyBtcAddress serializations are exact same size, figure it out now
      self.pybtcaddrSize = len(PyBtcAddress().serialize())


      # All BDM calls by default go on the multi-thread-queue.  But if the BDM
      # is the one calling the PyBtcWallet methods, it will deadlock if it uses
      # the queue.  Therefore, the BDM will set this flag before making any 
      # calls, which will tell PyBtcWallet to use __direct methods.
      self.calledFromBDM = False

      # Finally, a bunch of offsets that tell us where data is stored in the
      # file: this can be generated automatically on unpacking (meaning it
      # doesn't require manually updating offsets if I change the format), and
      # will save us a couple lines of code later, when we need to update things
      self.offsetWltFlags  = -1
      self.offsetLabelName = -1
      self.offsetLabelDescr  = -1
      self.offsetTopUsed   = -1
      self.offsetRootAddr  = -1
      self.offsetKdfParams = -1
      self.offsetCrypto    = -1
      """


   #############################################################################
   @VerifyArgTypes(keyData=[SecureBinaryData,None])
   def getPlainSeedCopy(self, keyData=None, kdfObj=None, ekeyObj=None):
      """
      NOTE:  This returns an SBD object which needs to be .destroy()ed by
             the caller when it is finished with it.
      """
      if self.seedCryptInfo.noEncryption():
         return self.sbdPrivKeyData.copy()

      aciDecryptAgs = self.getPrivCryptArgs(self.seedCryptInfo)

      # Override any args returned above with non-empty args to this func
      if not kdfObj is None:
         aciDecryptAgs['kdfObj'] = kdfObj

      if not ekeyObj is None:
         aciDecryptAgs['ekeyObj'] = ekeyObj
         
      try:
         return self.seedCryptInfo.decrypt( \
                  self.binPrivKey32_Encr, keyData, **aciDecryptAgs)
      except:
         LOGEXCEPT('Failed to decrypt private key')
         return NULLSBD()

   #############################################################################
   def CreateNewMasterRoot(self, typeStr='ARMORY20', cryptInfo=None, \
                                 kdfObj=None, ekeyObj=None, keyData=None, 
                                 seedBytes=20, extraEntropy=None):
      """
      The last few arguments identify how we plan to encrypt the seed and 
      master node information.  We plan to write this stuff to file right
      away, so we want to be able to encrypt it right away.  The cryptInfo
      object tells us how to encrypt it, and the ekeyObj, key and ivData
      objects are what is needed to encrypt the new seed and root immediately
      """


      if not typeStr=='BIP32':
         LOGERROR('Cannot create any roots other than BIP32 (yet)')
         raise NotImplementedError, 'Only BIP32 wallets allowed so far')

      self.rootType = typeStr
      self.wltVersion = ARMORY_WALLET_VERSION
      self.wltSource  = 'ARMORY'.ljust(12, '\x00')

      # Uses Crypto++ PRNG -- which is suitable for cryptographic purposes.
      # 16 bytes is generally considered enough, though we add 4 extra for 
      # some margin.  We also have the option to add some extra entropy 
      # through the last command line argument.  We use this in ArmoryQt
      # and armoryd by pulling key presses and volatile system files
      if extraEntropy is None:
         extraEntropy = NULLSBD() 

      self.bip32seed_plain  = SecureBinaryData().GenerateRandom(seedBytes, 
                                                                extraEntropy)

      LOGINFO('Computing extended key from seed')
      fullExtendedRoot = HDWalletCrypto().ConvertSeedToMasterKey(\
                                                   self.bip32seed_plain)
      
      self.binPrivKey32_Plain = fullExtendedRoot.getPriv()
      self.binPubKey33or65    = fullExtendedRoot.getPub()
      self.binAddr160         = fullExtendedRoot.getHash160().toBinStr()
      self.binChaincode       = fullExtendedRoot.getChain()
      

      # We have a 20-byte seed, but will need to be padded for 16-byte
      # blocksize if we ever need to encrypt it.
      self.seedNumBytes = self.bip32seed_plain.getSize()
      self.bip32seed_plain.padDataMod(cryptInfo.getBlockSize())
  

      # If no crypt info was designated, used default from this wallet file
      if cryptInfo is None:
         LOGINFO('No encryption requested, setting NULL encrypt objects')
         self.seedCryptInfo = ArmoryCryptInfo(None)
         self.bip32seed_encr = SecureBinaryData()
         self.binPrivKey32_Encr  = SecureBinaryData()
      else
         # Assume ivSource is CRYPT_IV_SRC.PUBKEY20[:16]
         self.privCryptInfo = cryptInfo.copy()
         self.seedCryptInfo = cryptInfo.copy()
         self.lock(  ekeyObj=ekeyObj, keyData=keyData)
         self.unlock(ekeyObj=ekeyObj, keyData=keyData)

            
      # FLAGS
      self.uniqueIDB58 = self.computeRootID()
      self.hdwChildID = -1
      self.hdwDepth = -1
      self.hdwIndexList = []
      self.lastComputedChainAddr160  = ''
      self.lastComputedChainIndex = 0
      self.highestUsedChainIndex  = 0 
      self.lastSyncBlockNum = 0
      self.isPhoneRoot = False  # don't send from, unless emergency sweep
      self.isSiblingRoot = False # observer root of a multi-sig wlt, don't use

   #############################################################################
   def getDepth(self):
      return len(self.derivePath)

   #############################################################################
   def getRootID(self, inBase58=True, nbytes=6):
      """ 
      We need some way to distinguish roots from one another, other than their
      20-byte hash.  Ideally, it will be distinct not only based on the Hash160
      value, but also based on the chaincode and chaining algorithm.  This way,
      if there are multiple variants/versions of code which are seeded with 
      the same data, but uses different algorithms, they will be distinguish-
      able.  It's also a good way to verify we are using the same algorithm as
      the code/app that originally produced this wallet.

      For this reason, if a wallet is labeled BIP32, we compute its child with
      index FFFFFFFF, take the first nbytes, and append the address byte to it
      (to identify the network, but put it in the back so that each root ID 
      has a different prefix character).
      """
      if not self.uniqueIDBin:
         endChild = self.spawnChild(0xFFFFFFFF)
         self.uniqueIDBin = endChild.getHash160()[:nbytes]+ADDRBYTE
         self.uniqueIDB58 = binary_to_base58(self.uniqueIDBin)

      return self.uniqueIDB58 if inBase58 else self.uniqueIDBin


   #############################################################################
   def getWalletChainIndex(self, chainType="External"):
      """
      In the case of single-sig wallets, we have just two chains, EXTERNAL (0)
      and INTERNAL (1).  In the case of multi-sig, we have one pair of wallet
      chains for each signing authority.  We use the ordering of the root pub
      keys in the relationship object to determine which of the 2*N chains to
      use.  This method will be overridden by the MultisigRoot class.
      """
      return 0 if chainType.lower()=='external' else 1

         

   #############################################################################
   def getNextUnusedAddrObj(self):
      if not self.getDepth()==2:
         raise WalletAddressError('Can only req new addrs from depth=2 nodes')
      
      # TODO:  Check that +1 is correct for hardened derivations, as well
      self.highestUsedChild += 1
      if self.highestUsedChild >= len(self.childList):
         self.spawnChild(self.highestUsedChild)

      childAddr = self.childList[self.highestUsedChild]
      childAddr.isUsed = True
      
      self.wltFileRef.addFileOperationToQueue('UpdateEntry', self)
      self.wltFileRef.addFileOperationToQueue('UpdateEntry', childAddr)
      self.wltFileRef.fsyncUpdates()
      
   
   

   #############################################################################
   lkjlkfdsj
   def spawnChild(self, childID, ekeyObj=None, keyData=None):
      """
      We require some fairly complicated logic here, due to the fact that a
      user with a full, private-key-bearing wallet, may try to generate a new
      key/address without supplying a passphrase.  If this happens, the wallet
      logic gets mucked up -- we don't want to reject the request to
      generate a new address, but we can't compute the private key until the
      next time the user unlocks their wallet.  Thus, we have to save off the
      data they will need to create the key, to be applied on next unlock.
      """
      
      TimerStart('spawnChild')

      if not self.hasChaincode():
         raise KeyDataError, 'No chaincode has been defined to extend chain'


      # If we have key data and it's encrypted, it's decrypted by now.
      # extchild has priv key if we have privavail == plain.  Else, we extend
      # only the public part
      if hdwDepth<3:
         childAddr = ArmoryRoot()
      else:
         childAddr = ArmoryAddress()
         
      childAddr.childIdentifier
      extChild  = HDWalletCrypto().ChildKeyDeriv(self.getExtendedKey(), childID)

      # In all cases we compute a new public key and chaincode
      childAddr.binPubKey33or65 = extChild.getPub().copy()
      childAddr.binChaincode    = extChild.getChain().copy()

      if privAvail==PRIV_KEY_AVAIL.Available:
         # We are extending a chain using private key data (unencrypted)
         childAddr.binPrivKey32_Plain  = extChild.getPriv().copy()
         childAddr.needToDerivePrivKey = False
      elif privAvail==PRIV_KEY_AVAIL.NextUnlock:
         # Copy the parent's encrypted key data to child, set flag
         childAddr.binPrivKey32_Encr = self.binPrivKey32_Encr.copy()
         childAddr.binChaincode      = self.binChaincode.copy()
         childAddr.needToDerivePrivKey = True
      elif privAvail==PRIV_KEY_AVAIL.None:
         # Probably just extending a public key
         childAddr.binPrivKey32_Plain  = SecureBinaryData(0)
         childAddr.needToDerivePrivKey = False
      else:
         LOGERROR('How did we get here?  spawnchild:')
         LOGERROR('   privAvail == %s', privAvail)
         LOGERROR('   encrypt   == %s', self.useEncryption)
         LOGERROR('Bailing without spawning child')
         raise KeyDataError
   
      childAddr.parentHash160      = self.getHash160()
      childAddr.binAddr160         = self.binPubKey33or65.getHash160()
      childAddr.useEncryption      = self.useEncryption
      childAddr.isInitialized      = True
      childAddr.childIdentifier    = childID
      childAddr.hdwDepth           = self.hdwDepth+1
      childAddr.indexList          = self.indexList[:]
      childAddr.indexList.append(childID)

      return childAddr




   #############################################################################
   @staticmethod
   def CreateNewJBOKRoot(self, cryptInfo=None):
      """
      JBOK is "just a bunch of keys," like the original Bitcoin-Qt client 
      (prior to version... 0.8?).   We don't actually need a deterministic 
      part in this root/chain... it's only holding a bunch of unrelated 
      """
      self.isFakeRoot = True
      self.privCryptInfo = cryptInfo.copy()

   #############################################################################
   @staticmethod
   def CreateNewBIP32_Root(self, 
      """
      JBOK is "just a bunch of keys," like the original Bitcoin-Qt client 
      (prior to version... 0.10?).  We don't actually need a deterministic 
      part in this root/chain... it's only holding a bunch of unrelated keys
      """
      self.privCryptInfo = cryptInfo.copy()


   #############################################################################
   def advanceHighestIndex(self, ct=1):
      topIndex = self.highestUsedChainIndex + ct
      topIndex = min(topIndex, self.lastComputedChainIndex)
      topIndex = max(topIndex, 0)

      self.highestUsedChainIndex = topIndex
      self.walletFileSafeUpdate( [[WLT_UPDATE_MODIFY, self.offsetTopUsed, \
                    int_to_binary(self.highestUsedChainIndex, widthBytes=8)]])
      self.fillAddressPool()
      
   #############################################################################
   def rewindHighestIndex(self, ct=1):
      self.advanceHighestIndex(-ct)


   #############################################################################
   def peekNextUnusedAddr160(self):
      return self.getAddress160ByChainIndex(self.highestUsedChainIndex+1)

   #############################################################################
   def getNextUnusedAddress(self):
      if self.lastComputedChainIndex - self.highestUsedChainIndex < \
                                              max(self.addrPoolSize-1,1):
         self.fillAddressPool(self.addrPoolSize)

      self.advanceHighestIndex(1)
      new160 = self.getAddress160ByChainIndex(self.highestUsedChainIndex)
      self.addrMap[new160].touch()
      self.walletFileSafeUpdate( [[WLT_UPDATE_MODIFY, \
                                  self.addrMap[new160].walletByteLoc, \
                                  self.addrMap[new160].serialize()]]  )

      return self.addrMap[new160]


   #############################################################################
   def changePrivateKeyEncryption(self, encryptInfoObj):
      

   #############################################################################
   def changeOuterEncryption(self, encryptInfoObj):


   #############################################################################
   def forkObserverChain(self, newWalletFile, shortLabel='', longLabel=''):



   #############################################################################
   def spawnChild(self, childID, decryptKey=None):
      """
      We require some fairly complicated logic here, due to the fact that a
      user with a full, private-key-bearing wallet, may try to generate a new
      key/address without supplying a passphrase.  If this happens, the wallet
      logic gets mucked up -- we don't want to reject the request to
      generate a new address, but we can't compute the private key until the
      next time the user unlocks their wallet.  Thus, we have to save off the
      data they will need to create the key, to be applied on next unlock.
      """

      
      TimerStart('spawnChild')

      if not self.hasChaincode():
         raise KeyDataError, 'No chaincode has been defined to extend chain'

      privAvail = self.getPrivKeyAvailability()
      if privAvail==PRIV_KEY_AVAIL.NextUnlock:
         LOGERROR('Cannot allow multi-level priv key generation while locked')
         LOGERROR('i.e. If your wallet has previously computed m/x and M/x,')
         LOGERROR('but it is currently encrypted, then it can spawn m/x/y by')
         LOGERROR('storing the encrypted version of m/x and its chaincode')
         LOGERROR('and then computing it on next unlock.  But if m/x/y is ')
         LOGERROR('currently in that state, you cannot then spawn m/x/y/z ')
         LOGERROR('until you have unlocked m/x/y once.  This is what is ')
         LOGERROR('meant by "multi-level key generation while locked')
         raise KeyDataError, 'Cannot do multi-level priv key gen while locked'
                              

      wasLocked  = False
      if privAvail==PRIV_KEY_AVAIL.NeedDecrypt:
         if not self.verifyEncryptionKey(decryptKey):
            raise PassphraseError, 'Incorrect passphrase entered to spawn child'
         else:
            self.unlock(decryptKey)
            privAvail = PRIV_KEY_AVAIL.Available
            wasLocked = True # will re-lock at the end of this operation

      # If we have key data and it's encrypted, it's decrypted by now.
      # extchild has priv key if we have privavail == Available.  Else, we extend
      # only the public part
      childAddr = ArmoryAddress()
      extChild  = HDWalletCrypto().ChildKeyDeriv(self.getExtendedKey(), childID)

      # In all cases we compute a new public key and chaincode
      childAddr.binPubKey33or65  = extChild.getPub().copy()
      childAddr.binChaincode     = extChild.getChain().copy()

      if privAvail==PRIV_KEY_AVAIL.Available:
         # We are extending a chain using private key data (unencrypted)
         childAddr.binPrivKey32_Plain  = extChild.getPriv().copy()
         childAddr.needToDerivePrivKey = False
      elif privAvail==PRIV_KEY_AVAIL.NextUnlock:
         # Copy the parent's encrypted key data to child, set flag
         childAddr.binPrivKey32_Encr = self.binPrivKey32_Encr.copy()
         childAddr.binChaincode      = self.binChaincode.copy()
         childAddr.needToDerivePrivKey = True
      elif privAvail==PRIV_KEY_AVAIL.None:
         # Probably just extending a public key
         childAddr.binPrivKey32_Plain  = SecureBinaryData(0)
         childAddr.needToDerivePrivKey = False
      else:
         LOGERROR('How did we get here?  spawnchild:')
         LOGERROR('   privAvail == %s', privAvail)
         LOGERROR('   encrypt   == %s', self.useEncryption)
         LOGERROR('Bailing without spawning child')
         raise KeyDataError
   
      childAddr.parentHash160    = extChild.getParentHash160().copy()
      childAddr.binAddr160       = self.binPubKey33or65.getHash160()
      childAddr.useEncryption    = self.useEncryption
      childAddr.isInitialized    = True
      childAddr.childIdentifier  = childID
      childAddr.hdwDepth         = self.hdwDepth+1
      childAddr.indexList        = self.indexList[:]
      childAddr.indexList.append(childID)
      childAddr.derivePathScheme = self.derivePathScheme[1:]

      return childAddr


################################################################################
class MultisigRoot(ArmoryRoot):
   # Replace RootRelationship with this...?
   """
   A simple structure for storing the fingerprints of all the siblings of 
   multi-sig wallet.  Each wallet chain that is part of this multi-sig 
   should store a multi-sig flag and the ID of this object.    If a chain
   has RRID zero but the multi-sig flag is on, it means that it was
   generated to be part of a multi-sig but not all siblings have been 
   acquired yet.

   This object can be transferred between wallets and will be ignored if
   none of the chains in the wallet use it.  Or transferred with all the
   public chains to fully communicate a watching-only version of the 
   multi-sig.  
   """
   FILECODE = 'MSRT'

   #############################################################################
   def __init__(self, M=None, N=None, siblingList=None, labels=None):
      super(MultisigRoot, self).__init__()

      self.M = M if M else 0
      self.N = N if N else 0
      self.relID       = NULLSTR(8)
      self.randID      = SecureBinaryData().GenerateRandom(8)
      self.sib160s     = []
      self.sibLabels   = []
      self.sibLookup   = []
      self.isComplete  = False
      self.siblingRefs = []


      if siblingList is None:
         siblingList = []

      if labels is None:
         labels = []

      if len(siblingList) > 15:
         raise MultisigError('Cannot have more than 15 wallets in multisig!')

      if not (self.N == len(siblingList) == len(labels)):
         raise MultisigError('Length of sibling list and labels must match N:'
                             ' N=%d, len(sibs)=%d, len(lbls)=%d' % \
                             (self.N, len(siblingList), len(labels))
         
      for sib,lbl in zip(siblingList, labels):
         if not len(sib)==20:
            raise MultisigError('All siblings must be 20-byte hash160 values')
         self.addSiblingID(sib,lbl)



   #############################################################################
   def getEntryID(self):
      self.relID = binary_to_base58(hash256(self.serializeMultisigData()))[:8]
      return self.relID

      
   #############################################################################
   def getWalletChainIndex(self, chainType="External"):
      # We have two chains for each sibling.  Pick the 
      indexSelf = self.getSiblingIndex(self.multisigWhoAmI())
      return 2*indexSelf + (0 if chainType.lower()=='external' else 1)

   #############################################################################
   def multisigWhoAmI(self):
      LOGERROR('TODO: implement proper chain-selection for multisig wallets!')
      return self.sib160s[0]


   #############################################################################
   def addSiblingID(self, sibRootID, label):
      if len(self.sib160s) >= self.N:
         raise BadInputError('RR already has %d siblings' % self.N)

      self.sib160s.append(sibRootID)
      self.sibLabels.append(label)
      self.siblingRefs.append(None)

      if len(self.sib160s) == self.N:
         self.isComplete = True
         self.sib160s.sort()
         for i,sib in enumerate(self.sib160s):
            self.sibLookup[sib] = i
          
   #############################################################################
   def setSiblingRef(self, sibRef):
      if not self.isComplete: 
         raise MultisigError('Cannot add sibling refs until all IDs are added')
      i = getSiblingIndex(sibRef.getEntryID())
      self.siblingRefs[i] = sibRef

   #############################################################################
   def getSiblingIndex(self, sibID):
      if not self.isComplete:
         raise UninitializedError('Multisig root object not full yet')

      if not sibID in self.sibLookup:
         raise UninitializedError('Sibling not found in this root obj')
          
      return self.sibLookup[sibID]
      

   #############################################################################
   def serializeMultisigData(self):
      bp = BinaryPacker()
      bp.put(BINARY_CHUNK, self.relID, widthBytes=8)
      bp.put(BINARY_CHUNK, self.randID, widthBytes=8)
      bp.put(UINT8, self.M)
      bp.put(UINT8, self.N)
      bp.put(UINT8, len(self.sib160s))
      for i in range(len(self.sib160s)):
         bp.put(VAR_STR, self.sib160s[i])
         bp.put(VAR_UNICODE, self.labels[i])

      return bp.getBinaryString()


   #############################################################################
   def unserializeMultisigData(self, theStr):
      bu = makeBinaryUnpacker(theStr)
      relID = bu.get(BINARY_CHUNK, 8)
      rndID = bu.get(BINARY_CHUNK, 8)
      M = bu.get(UINT8)
      N = bu.get(UINT8)
      nsib = bu.get(UINT8)
      sibList = []
      lblList = []
      for i in range(nsib):
         sibList.append(bu.get(VAR_STR))
         lblList.append(bu.get(VAR_UNICODE))

      self.__init__(M, N, sibList, lblList)
      return self

   #############################################################################
   def serialize(self):
      bp = BinaryPacker()
      bp.put(BINARY_CHUNK, super(MultisigRoot, self).serialize())
      bp.put(BINARY_CHUNK, self.serializeMultisigData())

   #############################################################################
   def unserialize(self, theStr):
      bu = makeBinaryUnpacker(theStr)




################################################################################
class ArbitraryDataContainer(WalletEntry):

   self.




# We should have all the classes availale by now, we can add the 
# class list to the WalletEntry static members
ISREQUIRED=True
WalletEntry.addClassToMap('ROOT', ArmoryRoot, ISREQUIRED)
WalletEntry.addClassToMap('ALBL', AddressLabel)
WalletEntry.addClassToMap('TLBL', TxLabel)
WalletEntry.addClassToMap('LBOX', MultiSigLockbox)
WalletEntry.addClassToMap('RLAT', RootRelationship, ISREQUIRED)
WalletEntry.addClassToMap('EKEY', EncryptionKey)
WalletEntry.addClassToMap('MKEY', MultiPwdEncryptionKey)
WalletEntry.addClassToMap('KDF_', KdfObject)
WalletEntry.addClassToMap('IDNT', IdentityPublicKey)
WalletEntry.addClassToMap('SIGN', WltEntrySignature)
WalletEntry.addClassToMap('DATA', ArbitraryDataContainer)
