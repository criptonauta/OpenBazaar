import logging
import random
import time

import constants
import guid
import kbucket


class RoutingTable(object):
    """
    Interface for RPC message translators/formatters.

    Classes inheriting from this should provide a suitable routing table
    for a parent Node object (i.e. the local entity in the Kademlia
    network).
    """

    def __init__(self, parent_node_id, market_id):
        """
        Initialize a new RoutingTable.

        @param parent_node_id: The node ID of the node to which this
                               routing table belongs.
        @type parent_node_id: guid.GUIDMixin or str or unicode

        @param market_id: FILLME
        @type: int
        """
        self.market_id = market_id
        self.parent_node_id = parent_node_id

        self.log = logging.getLogger(
            '[%s] %s' % (self.market_id, self.__class__.__name__)
        )

    def addContact(self, node_id):
        """
        Add the given node to the correct KBucket; if it already
        exists, update its status.

        @param contact: The contact to add to this node's KBuckets
        @type contact: guid.GUIDMixin or str or unicode
        """
        raise NotImplementedError

    @staticmethod
    def distance(keyOne, keyTwo):
        """
        Calculate the XOR result between two string variables.

        @return: XOR result of two long variables
        @rtype: long
        """
        valKeyOne = long(keyOne.encode('hex'), 16)
        valKeyTwo = long(keyTwo.encode('hex'), 16)
        return valKeyOne ^ valKeyTwo

    def findCloseNodes(self, node_id, count, rpc_node_id=None):
        """
        Find a number of known nodes closest to the node/value with the
        specified ID.

        @param node_id: The node ID to search for
        @type node_id: guid.GUIDMixin or str or unicode

        @param count: The amount of contacts to return
        @type count: int

        @param rpc_node_id: Used during RPC, this is the sender's node ID.
                            The ID passed as parameter is excluded from
                            the list of returned contacts.
        @type rpc_node_id: guid.GUIDMixin or str or unicode

        @return: A list of nodes closest to the specified key.
                 This method will return constants.k (or count, if
                 specified) contacts if at all possible; it will only
                 return fewer if the node is returning all of the
                 contacts that it knows of.
        @rtype: list of guid.GUIDMixin
        """
        raise NotImplementedError

    def getContact(self, node_id):
        """
        Return the known node with the specified ID, None if not found.

        @param: node_id: The ID of the node to search for.
        @type: guid.GUIDMixin or str or unicode

        @return: The node with the specified ID or None
        @rtype: guid.GUIDMixin or NoneType
        """
        raise NotImplementedError

    def getRefreshList(self, start_index=0, force=False):
        """
        Find all KBuckets that need refreshing, starting at the KBucket
        with the specified index, and return IDs to be searched for in
        order to refresh those KBuckets.

        @param start_index: The index of the bucket to start refreshing
                            at; this bucket and those further away from
                            it will be refreshed. For example, when
                            joining the network, this node will set this
                            to the index of the bucket after the one
                            containing its closest neighbour.
        @type start_index: int

        @param force: If this is True, all buckets in the specified
                      range will be refreshed, regardless of the time
                      they were last accessed.
        @type force: bool

        @return: A list of node IDs that the parent node should search for
                 in order to refresh the routing Table.
        @rtype: list of guid.GUIDMixin
        """
        raise NotImplementedError

    def removeContact(self, node_id):
        """
        Remove the node with the specified ID from the routing table.

        @param node_id: The ID of the node to remove.
        @type node_id: guid.GUIDMixin or str or unicode
        """
        raise NotImplementedError

    def touchKBucket(self, node_id):
        """
        Update the "last accessed" timestamp of the KBucket which covers
        the range containing the specified key in the key/ID space.

        @param node_id: A key in the range of the target KBucket
        @type node_id: guid.GUIDMixin or str or unicode
        """
        raise NotImplementedError


class TreeRoutingTable(RoutingTable):
    """
    This class implements a routing table used by a Node class.

    The Kademlia routing table is a binary tree whose leaves are KBuckets,
    where each KBucket contains nodes with some common prefix of their IDs.
    This prefix is the KBucket's position in the binary tree; it therefore
    covers some range of ID values, and together all of the KBuckets cover
    the entire ID space, without any overlaps.

    @note: In this implementation, nodes in the tree (the KBuckets) are
    added dynamically, as needed; this technique is described in the 13-page
    version of the Kademlia paper, in section 2.4. It does, however, use the
    PING RPC-based KBucket eviction algorithm described in section 2.2 of
    that paper.
    """

    def __init__(self, parent_node_id, market_id):
        """
        Initialize a new TreeRoutingTable.

        For details, see RoutingTable documentation.
        """
        super(TreeRoutingTable, self).__init__(parent_node_id, market_id)

        self.buckets = [
            kbucket.KBucket(
                rangeMin=0,
                rangeMax=2**BIT_NODE_ID_LEN,
                market_id=market_id
            )
        ]

    def addContact(self, contact):
        """
        Add the given contact to the correct k-bucket; if it already
        exists, update its status.

        @param contact: The contact to add to this node's k-buckets
        @type contact: guid.GUIDMixin or str or unicode
        """

        # If contact is itself return
        if contact.guid == self.parent_node_id:
            return

        bucketIndex = self.kbucketIndex(contact.guid)

        # If already added then update
        if not self.buckets[bucketIndex].getContact(contact):

            try:
                self.buckets[bucketIndex].addContact(contact)
            except kbucket.BucketFull:
                # The bucket is full; see if it can be split (by checking if
                # its range includes the host node's id)
                if self.buckets[bucketIndex].keyInRange(self.parent_node_id):
                    self.splitBucket(bucketIndex)
                    # Retry the insertion attempt
                    self.addContact(contact)
                else:
                    # We can't split the k-bucket
                    # NOTE:
                    # In section 2.4 of the 13-page version of the Kademlia
                    # paper, it is specified that in this case, the new
                    # contact should simply be dropped. However, in
                    # section 2.2, it states that the head contact in the
                    # k-bucket (i.e. the least-recently seen node) should be
                    # pinged - if it does not reply, it should be dropped, and
                    # the new contact added to the tail of the k-bucket. This
                    # implementation follows section 2.2 regarding this point.

                    def replaceContact(failure):
                        """Callback for the deferred PING RPC to see if the
                           head node in the k-bucket is still responding
                           """
                        failure.trap(TimeoutError)
                        print '==replacing contact=='
                        # Remove the old contact...
                        deadContactID = failure.getErrorMessage()
                        try:
                            bucket = self.buckets[bucketIndex]
                            bucket.removeContact(deadContactID)
                        except ValueError:
                            # The contact has already been removed (probably
                            # due to a timeout)
                            pass
                        # ...and add the new one at the tail of the bucket
                        self.addContact(contact)

                    # Ping the least-recently seen contact in this k-bucket
                    headContact = self.buckets[bucketIndex].contacts[0]

                    # headContact.send({
                    #     "type": "ping",
                    #     "guid": self.guid,
                    #     "uri": self._uri,
                    #     "findValue": peer['findValue']
                    # })

                    df = headContact.ping()
                    # If there's an error (i.e. timeout), remove the head
                    # contact, and append the new one
                    df.addErrback(replaceContact)

    def findCloseNodes(self, key, count, nodeID=None):
        """
        Find a number of known nodes closest to the node/value with the
        specified key.

        @param key: The key (i.e. the node or value ID) to search for.
        @type key: str

        @param count: the amount of contacts to return
        @type count: int
        @param nodeID: Used during RPC, this is the sender's Node ID.
                       The ID passed in the paramater is excluded from
                       the list of contacts returned.
        @type nodeID: str

        @return: A list of node contacts (C{guid.GUIDMixin instances})
                 closest to the specified key.
                 This method will return C{k} (or C{count}, if specified)
                 contacts if at all possible; it will only return fewer if the
                 node is returning all of the contacts that it knows of.
        @rtype: list
        """
        bucketIndex = self.kbucketIndex(key)
        bucket = self.buckets[bucketIndex]
        closestNodes = bucket.getContacts(constants.k, node_id)

        # This method must return k contacts (even if we have the node with
        # the specified key as node ID), unless there is less than k remote
        # nodes in the routing table.
        i = 1
        canGoLower = bucketIndex - i >= 0
        canGoHigher = bucketIndex + i < len(self.buckets)
        # Fill up the node list to k nodes, starting with the closest
        # neighbouring nodes known.
        while len(closestNodes) < constants.k and (canGoLower or canGoHigher):
            # TODO: this may need to be optimized
            if canGoLower:
                bucket = self.buckets[bucketIndex - i]
                closestNodes.extend(
                    bucket.getContacts(
                        constants.k - len(closestNodes), node_id
                    )
                )
                canGoLower = bucketIndex - (i + 1) >= 0
            if canGoHigher:
                bucket = self.buckets[bucketIndex + i]
                closestNodes.extend(
                    bucket.getContacts(
                        constants.k - len(closestNodes), node_id
                    )
                )
                canGoHigher = bucketIndex + (i + 1) < len(self.buckets)
            i += 1

        self.log.debug('Closest Nodes: %s' % closestNodes)
        return closestNodes

    def getContact(self, contactID):
        """
        Return the (known) contact with the specified node ID.

        @raise ValueError: This node knows no contact with
                           the specified contact ID.
        """

        bucketIndex = self.kbucketIndex(contactID)

        try:
            contact = self.buckets[bucketIndex].getContact(contactID)
        except ValueError:
            raise
        else:
            return contact

    def getRefreshList(self, startIndex=0, force=False):
        """
        Find all k-buckets that need refreshing, starting at the
        k-bucket with the specified index, and return IDs to be searched for
        in order to refresh those k-buckets.

        @param startIndex: The index of the bucket to start refreshing at;
                           this bucket and those further away from it will
                           be refreshed. For example, when joining the
                           network, this node will set this to the index of
                           the bucket after the one containing its closest
                           neighbour.
        @type startIndex: index

        @param force: If this is C{True}, all buckets (in the specified range)
                      will be refreshed, regardless of the time they were last
                      accessed.
        @type force: bool

        @return: A list of node ID's that the parent node should search for
                 in order to refresh the routing Table
        @rtype: list
        """
        bucketIndex = startIndex
        refreshIDs = []
        for bucket in self.buckets[startIndex:]:
            if force or \
               int(time.time()) - bucket.lastAccessed >= constants.refreshTimeout:
                searchID = self._randomIDInBucketRange(bucketIndex).encode('hex')
                refreshIDs.append(searchID)
            bucketIndex += 1
        return refreshIDs

    def removeContact(self, contactID):
        """
        Remove the contact with the specified node ID from the routing table.

        @param contactID: The node ID of the contact to remove
        @type contactID: guid.GUIDMixin or str or unicode
        """
        bucketIndex = self.kbucketIndex(contactID)
        try:
            self.buckets[bucketIndex].removeContact(contactID)
        except ValueError:
            # print 'removeContact(): Contact not in routing table'
            return

    def touchKBucket(self, key):
        """
        Update the "last accessed" timestamp of the k-bucket which covers
        the range containing the specified key in the key/ID space.

        @param key: A key in the range of the target k-bucket
        @type key: str
        """
        bucketIndex = self.kbucketIndex(key)
        self.buckets[bucketIndex].lastAccessed = int(time.time())

    def kbucketIndex(self, node_id):
        """
        Calculate the index of the KBucket which is responsible for the
        specified key (or ID).

        @param key: The key for which to find the appropriate KBucket index
        @type key: guid.GUIDMixin or str or unicode

        @raises: KeyError: The key was no KBucket's responsibility; absent key.
                 RuntimeError: Many KBuckets responsible for same key;
                               invariants have been violated.
                 ValueError: The key is badly encoded.

        @return: The index of the KBucket responsible for the specified key
        @rtype: int
        """
        if isinstance(node_id, guid.GUIDMixin):
            key = node_id.guid
        else:
            key = node_id

        # TODO: Since we are using monotonic node ID spaces,
        # this *begs* to be done with binary search.
        indexes = [
            i
            for i, bucket in enumerate(self.buckets)
            if bucket.keyInRange(key)
        ]

        if not indexes:
            raise KeyError("No KBucket responsible for key %s." % key)
        elif len(indexes) > 1:
            raise RuntimeError(
                "Many KBuckets responsible for key %s." % key
            )
        return indexes[0]

    def _randomIDInBucketRange(self, bucketIndex):
        """
        Returns a random ID in the specified k-bucket's range.

        @param bucketIndex: The index of the k-bucket to use
        @type bucketIndex: int
        """
        idValue = random.randrange(
            self.buckets[bucketIndex].rangeMin,
            self.buckets[bucketIndex].rangeMax
        )
        randomID = hex(idValue)[2:]
        if randomID[-1] == 'L':
            randomID = randomID[:-1]
        if len(randomID) % 2 != 0:
            randomID = '0' + randomID
        randomID = randomID.decode('hex')
        randomID = (20 - len(randomID)) * '\x00' + randomID
        return randomID

    def splitBucket(self, oldBucketIndex):
        """
        Split the specified k-bucket into two new buckets which together cover
        the same range in the key/ID space.

        @param oldBucketIndex: The index of k-bucket to split (in this table's
                               list of k-buckets)
        @type oldBucketIndex: int
        """
        # Halve the range of the current (old) k-bucket.
        oldBucket = self.buckets[old_bucket_index]
        splitPoint = oldBucket.rangeMax - (oldBucket.rangeMax - oldBucket.rangeMin) / 2
        # Create a new k-bucket to cover the range split off from the old one.
        newBucket = kbucket.KBucket(
            splitPoint, oldBucket.rangeMax, self.market_id
        )
        oldBucket.rangeMax = splitPoint
        # Now, add the new bucket into the routing table tree
        self.buckets.insert(old_bucket_index + 1, newBucket)
        # Finally, copy all nodes that belong to the new k-bucket into it...
        for contact in oldBucket.contacts:
            if newBucket.keyInRange(contact.guid):
                newBucket.addContact(contact)
        # ...and remove them from the old bucket
        for contact in newBucket.contacts:
            oldBucket.removeContact(contact)


class OptimizedTreeRoutingTable(TreeRoutingTable):
    """
    A version of the "tree"-type routing table specified by Kademlia,
    along with contact accounting optimizations specified in section 4.1 of
    of the 13-page version of the Kademlia paper.
    """

    def __init__(self, parent_node_id, market_id):
        """
        Initialize a new OptimizedTreeRoutingTable.

        For details, see TreeRoutingTable documentation.
        """
        super(OptimizedTreeRoutingTable, self).__init__(
            parent_node_id, market_id
        )

        # Cache containing nodes eligible to replace stale k-bucket entries
        self.replacement_cache = {}

    def addContact(self, contact):
        """
        Add the given contact to the correct k-bucket; if it already
        exists, update its status.

        @param contact: The contact to add to this node's k-buckets
        @type contact: guid.GUIDMixin or str or unicode
        """

        if not contact.guid:
            self.log.error('No guid specified')
            return

        if contact.guid == self.parent_node_id:
            self.log.info('Trying to add yourself. Leaving.')
            return

        # Initialize/reset the "successively failed RPC" counter
        contact.failedRPCs = 0

        bucketIndex = self.kbucketIndex(contact.guid)

        old_contact = self.buckets[bucketIndex].getContact(contact.guid)

        if not old_contact:

            try:
                self.buckets[bucketIndex].addContact(contact)
            except kbucket.BucketFull:
                # The bucket is full; see if it can be split (by checking if
                # its range includes the host node's id)
                if self.buckets[bucketIndex].keyInRange(self.parent_node_id):
                    self.splitBucket(bucketIndex)
                    # Retry the insertion attempt
                    self.addContact(contact)
                else:
                    # We can't split the k-bucket
                    # NOTE: This implementation follows section 4.1 of the 13
                    # page version of the Kademlia paper (optimized contact
                    # accounting without PINGs - results in much less network
                    # traffic, at the expense of some memory)

                    # Put the new contact in our replacement cache for the
                    # corresponding k-bucket (or update it's position if it
                    # exists already)
                    if bucketIndex not in self.replacement_cache:
                        self.replacement_cache[bucketIndex] = []
                    if contact in self.replacement_cache[bucketIndex]:
                        self.replacement_cache[bucketIndex].remove(contact)
                    # TODO: Using k to limit the size of the contact
                    # replacement cache - maybe define a separate value for
                    # this in constants.py?
                    elif len(self.replacement_cache) >= constants.k:
                        self.replacement_cache.pop(0)
                    self.replacement_cache[bucketIndex].append(contact)

        else:
            if old_contact.address != contact.address:

                self.log.info('Remove contact')
                self.removeContact(contact.guid)

                try:
                    self.buckets[bucketIndex].addContact(contact)
                except kbucket.BucketFull:
                    # The bucket is full; see if it can be split (by checking
                    # if its range includes the host node's id)
                    if self.buckets[bucketIndex].keyInRange(self.parent_node_id):
                        self.splitBucket(bucketIndex)
                        # Retry the insertion attempt
                        self.addContact(contact)
                    else:
                        # We can't split the k-bucket
                        # NOTE: This implementation follows section 4.1 of the
                        # 13 page version of the Kademlia paper (optimized
                        # contact accounting without PINGs - results in much
                        # less network traffic, at the expense of some memory)

                        # Put the new contact in our replacement cache for the
                        # corresponding k-bucket (or update it's position if
                        # it exists already)
                        if bucketIndex not in self.replacement_cache:
                            self.replacement_cache[bucketIndex] = []
                        if contact in self.replacement_cache[bucketIndex]:
                            self.replacement_cache[bucketIndex].remove(contact)
                        # TODO: Using k to limit the size of the contact
                        # replacement cache - maybe define a separate value
                        # for this in constants.py?
                        elif len(self.replacement_cache) >= constants.k:
                            self.replacement_cache.pop(0)
                        self.replacement_cache[bucketIndex].append(contact)

    def removeContact(self, contactID):
        """
        Remove the contact with the specified node ID from the routing table.

        @param contactID: The node ID of the contact to remove
        @type contactID: str
        """
        bucketIndex = self.kbucketIndex(contactID)
        try:
            self.buckets[bucketIndex].removeContact(contactID)
        except ValueError:
            pass
            # print 'removeContact(): Contact not in routing table'
        else:
            # Replace this stale contact with one from our replacement
            # cache, if we have any.
            if bucketIndex in self.replacementCache:
                if len(self.replacement_cache[bucketIndex]) > 0:
                    self.buckets[bucketIndex].addContact(
                        self.replacement_cache[bucketIndex].pop()
                    )

            self.log.debug(
                'Contacts: %s' % self.buckets[bucketIndex].contacts
            )
