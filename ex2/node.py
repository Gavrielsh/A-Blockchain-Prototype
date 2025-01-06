import hashlib
import secrets

from .utils import *
from .block import Block
from .transaction import Transaction
from typing import Set, Optional, List

class Node:
    def __init__(self) -> None:
        self.private_key, self.public_key = gen_keys()
        self.mempool: List[Transaction] = []  # list of transactions waiting to be mined
        self.connections: Set[Node] = set()  # connected nodes
        self.blocks: dict[BlockHash, Block] = {}  # list of blocks known to this node
        self.latest_block_hash: BlockHash = GENESIS_BLOCK_PREV  # latest block hash in the chain
        self.utxo: List[Transaction] = []  # list of unspent transactions

    def connect(self, other: 'Node') -> None:
        # if other is self cannot connect to itself
        if other == self:
            raise ValueError("Node cannot connect to itself.")
        # add the other node to the connections set
        self.connections.add(other)
        # add self to the other node connections set
        other.connections.add(self)
        # notify the other node of the latest block
        other.notify_of_block(self.latest_block_hash, self)

    def disconnect_from(self, other: 'Node') -> None:
        # remove the other node from the connections set
        self.connections.discard(other)
        # remove self from the other node connections set
        other.connections.discard(self)

    def get_connections(self) -> Set['Node']:
        return self.connections

    def add_transaction_to_mempool(self, transaction: Transaction) -> bool:
        """
        This function inserts the given transaction to the mempool.
        It will return False iff any of the following conditions hold:
        (i) the transaction is invalid (the signature fails)
        (ii) the source doesn't have the coin that it tries to spend
        (iii) there is contradicting tx in the mempool.

        If the transaction is added successfully, then it is also sent to neighboring nodes.
        """
        # make sure the transaction is valid
        if not verify(transaction.get_txid(), transaction.signature, transaction.output):
            return False
        # make sure the transaction is not already in the mempool
        if transaction.input and transaction.input not in [tx.get_txid() for tx in self.utxo]:
            return False

        # update UTXO
        self.utxo = [tx for tx in self.utxo if tx.get_txid() != transaction.input]
        # add the transaction to the UTXO
        self.mempool.append(transaction)
        # send the transaction to the connected nodes
        for node in self.connections:
            node.add_transaction_to_mempool(transaction)

        return True

    def notify_of_block(self, block_hash: BlockHash, sender: 'Node') -> None:
        """Notifies the node about a new block while allowing valid blocks to be added."""
        if block_hash in self.blocks:
            print(f"[DEBUG] Block {block_hash} already known.")
            return

        # Temporary storage for validated blocks
        valid_blocks = []
        current_hash = block_hash


        while current_hash != GENESIS_BLOCK_PREV and current_hash not in self.blocks:
            try:
                block = sender.get_block(current_hash)
            except ValueError:
                print(f"[DEBUG] Could not retrieve block {current_hash}. Stopping processing.")
                break


            if self._is_valid_block(block):
                valid_blocks.append(block)
            else:
                print(f"[DEBUG] Invalid block {block.get_block_hash()}. Ignoring this block.")
                break  # Stop further processing when encountering an invalid block

            current_hash = block.get_prev_block_hash()


        # Add valid blocks in reverse order to maintain chain order
        for block in reversed(valid_blocks):
            self.blocks[block.get_block_hash()] = block
            if current_hash == GENESIS_BLOCK_PREV:
                valid_blocks.append(block)
            else:
                print(f"[DEBUG] Chain does not lead to genesis. Stopping processing.")
                break

        # Check if this is now the longest chain
        if self._get_chain_length(block_hash) > self._get_chain_length(self.latest_block_hash):
            self._reorganize_chain(block_hash)

        # Notify neighbors about the latest valid block
        if valid_blocks and valid_blocks[-1].get_block_hash() == self.latest_block_hash:
            for neighbor in self.connections:
                neighbor.notify_of_block(self.latest_block_hash, self)

    def _is_valid_block(self, block: Block) -> bool:
        """
        Validates a block based on its hash, size, and transactions.
        """
        # Validate block hash
        expected_hash = BlockHash(hashlib.sha256(
            block.get_prev_block_hash() + b''.join(tx.get_txid() for tx in block.get_transactions())
        ).digest())
        if block.get_block_hash() != expected_hash:
            print(f"[DEBUG] Invalid block hash for {block.get_block_hash()}.")
            return False

        # Check block size
        if len(block.get_transactions()) > BLOCK_SIZE:
            print(f"[DEBUG] Block {block.get_block_hash()} exceeds block size limit.")
            return False

        # Validate transactions
        reward_tx_count = 0
        seen_txids = set()
        for tx in block.get_transactions():
            if tx.get_txid() in seen_txids:
                print(f"[DEBUG] Duplicate transaction {tx.get_txid()} in block.")
                return False
            seen_txids.add(tx.get_txid())

            if tx.input is None:  # Reward transaction
                reward_tx_count += 1
            else:
                if not self._find_tx_in_utxo(tx):
                    print(f"[DEBUG] Transaction {tx.get_txid()} references a non-existent or spent input.")
                    return False
                if not verify(tx.input + tx.output, tx.signature, tx.output):
                    print(f"[DEBUG] Transaction {tx.get_txid()} has an invalid signature.")
                    return False

        # Ensure only one reward transaction
        if reward_tx_count != 1:
            print(f"[DEBUG] Invalid number of reward transactions in block {block.get_block_hash()}.")
            return False

        return True

    def _get_chain_length(self, block_hash: BlockHash) -> int:
        """
        Computes the length of the chain ending at the given block hash.
        """
        length = 0
        current_hash = block_hash
        while current_hash in self.blocks:
            block = self.blocks[current_hash]
            current_hash = block.get_prev_block_hash()
            length += 1
        return length

    def _reorganize_chain(self, new_tip: BlockHash) -> None:
        split_point = self._find_split_point(self.latest_block_hash, new_tip)
        self._rollback_to_split_point(split_point)

        # recognize stale transactions that need to be removed from the mempool
        stale_txs = {tx.get_txid() for block in self._get_chain_to_tip(self.latest_block_hash, split_point)
                     for tx in block.get_transactions()}

        # Roll forward the chain
        current_hash = new_tip
        new_chain = []
        while current_hash != split_point:
            block = self.blocks[current_hash]
            new_chain.append(block)
            current_hash = block.get_prev_block_hash()
        # Reverse the chain to process it from the split point to the new tip
        new_chain.reverse()
        for block in new_chain:
            for tx in block.get_transactions():
                if tx.input:
                    self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.input]
                self.utxo.append(tx)
                stale_txs.discard(tx.get_txid())

        self.latest_block_hash = new_tip

        # Remove stale transactions from the mempool and add the remaining transactions back
        for tx in self.mempool:
            if tx.get_txid() not in stale_txs:
                self.mempool.append(tx)

        print(f"[DEBUG] Chain reorganized to new tip: {new_tip}")

    def _rollback_to_split_point(self, split_point: BlockHash) -> None:

        current_hash = self.latest_block_hash
        # while the current hash is not the split point roll back the chain
        while current_hash != split_point:
            if current_hash not in self.blocks:
                raise ValueError(f"Block {current_hash} is missing in the chain.")
            # get the block from the blocks dictionary
            block = self.blocks[current_hash]
            # for each transaction in the block
            for tx in block.get_transactions():
                # if the transaction is in the UTXO remove it
                if tx.get_txid() in [utxo_tx.get_txid() for utxo_tx in self.utxo]:
                    # remove the transaction from the UTXO
                    self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.get_txid()]
                if tx.input:  # Add back transactions that were rolled back and can still be executed
                    self.mempool.append(tx)
            # remove the block from the blocks dictionary
            current_hash = block.get_prev_block_hash()

    def _find_split_point(self, hash1: BlockHash, hash2: BlockHash) -> BlockHash:
        """
        Finds the common ancestor (split point) between two chains.
        """
        seen_hashes = set()

        # Traverse both chains until a common ancestor is found
        while hash1 or hash2:
            # If a common ancestor is found, return it
            if hash1 in seen_hashes:
                return hash1
            if hash2 in seen_hashes:
                return hash2
            # Traverse the first chain
            if hash1 is not None:
                seen_hashes.add(hash1)
                hash1 = self.blocks[hash1].get_prev_block_hash() if hash1 in self.blocks else None
            # Traverse the second chain
            if hash2 is not None:
                seen_hashes.add(hash2)
                hash2 = self.blocks[hash2].get_prev_block_hash() if hash2 in self.blocks else None

        # If no common ancestor is found, return the genesis block
        return GENESIS_BLOCK_PREV

    def mine_block(self) -> Optional[BlockHash]:
        """
        This function allows the node to create a single block.
        - The block should contain BLOCK_SIZE transactions (unless there aren't enough in the mempool).
        Of these,
        BLOCK_SIZE-1 transactions come from the mempool and one addtional transaction will be included that creates
        money and adds it to the address of this miner.
        - Money creation transactions have None as their input, and instead of a signature, contain 48 random bytes.
        - If a new block is created, all connections of this node are notified by calling their notify_of_block() method.
        The method returns the new block hash (or None if there was no block)
        """
        selected_transactions = self.mempool[:BLOCK_SIZE - 1]
        reward_transaction = Transaction(
            output=self.get_address(),
            tx_input=None,
            signature=Signature(secrets.token_bytes(48))
        )

        transactions = selected_transactions + [reward_transaction]
        new_block = Block(
            prev_block_hash=self.latest_block_hash,
            transactions=transactions
        )

        block_hash = new_block.get_block_hash()
        self.blocks[block_hash] = new_block
        self.latest_block_hash = block_hash

        # update UTXO with the new block's transactions and remove them from the mempool
        existing_txids = {tx.get_txid() for tx in self.utxo}
        for tx in transactions:
            # only add transactions that are not already in the UTXO
            if tx.get_txid() not in existing_txids:
                self.utxo.append(tx)
                existing_txids.add(tx.get_txid())
                self.mempool = self.mempool[BLOCK_SIZE - 1:]

        for neighbor in self.connections:
            neighbor.notify_of_block(block_hash, self)

        return block_hash

    def _find_tx_in_utxo(self, tx: Transaction) -> bool:
        """
        Check if a transaction exists in the UTXO based on its TXID.
        """
        # Check if the transaction is in the UTXO
        return any(utxo_tx.get_txid() == tx.get_txid() for utxo_tx in self.utxo)

    def get_block(self, block_hash: BlockHash) -> Block:
        """
        Returns a block object given its hash.
        Raises ValueError if the block doesn't exist.
        """
        if block_hash not in self.blocks:
            raise ValueError(f"Block with hash {block_hash} does not exist.")
        return self.blocks[block_hash]

    def get_latest_hash(self) -> BlockHash:
        """
        Returns the hash of the latest block in the current chain.
        """
        return self.latest_block_hash

    def get_mempool(self) -> List[Transaction]:
        """
        Returns the list of transactions in the mempool.
        """
        return self.mempool

    def get_utxo(self) -> List[Transaction]:
        """
        Returns a copy of the list of unspent transactions (UTXO).
        """
        return self.utxo.copy()
    # ------------ Formerly wallet methods: -----------------------

    def create_transaction(self, target: PublicKey) -> Optional[Transaction]:
        """
        Returns a signed transaction that moves an unspent coin to the target.
        Returns None if there are no unspent coins available.
        """
        # search for an unspent transaction
        for tx in self.utxo:
            if not any(mempool_tx.input == tx.get_txid() for mempool_tx in self.mempool):
                # create a new transaction
                txid = tx.get_txid()
                private_key = self.private_key  # the private key of the sender
                signature = sign(txid, private_key) # sign the transaction ID
                # create a new transaction
                new_transaction = Transaction(
                    output=target,
                    tx_input=txid,
                    signature=signature
                )

                # add the transaction to the mempool
                self.add_transaction_to_mempool(new_transaction)

                return new_transaction

        # if there is no unspent transaction
        return None

    def clear_mempool(self) -> None:
        """
        Clears the mempool of this node. All transactions waiting to be entered into the next block are gone.
        """
        self.mempool = []

    def get_balance(self) -> int:
        """
        Returns the number of coins this node owns according to its view of the blockchain.
        Coins that the node owned and sent away will still be considered as part of the balance
        until the spending transaction is in the blockchain.
        """
        balance = 0
        for tx in self.utxo:
            if tx.output == self.public_key:
                balance += 1  # each transaction is worth 1 coin
        return balance

    def get_address(self) -> PublicKey:
        """
        Returns the public address of this node (its public key).
        """
        return self.public_key

    def _get_chain_to_tip(self, latest_block_hash: BlockHash, split_point: BlockHash) -> List[Block]:
        """
        Returns the chain of blocks from the latest block hash to the split point.
        The blocks are returned in reverse order (from tip to split point).

        Args:
            latest_block_hash (BlockHash): The hash of the latest block in the current chain.
            split_point (BlockHash): The hash of the split point in the chain.

        Returns:
            List[Block]: The list of blocks in reverse order from the latest block to the split point.
        """
        chain = []
        current_hash = latest_block_hash

        while current_hash != split_point:
            if current_hash not in self.blocks:
                raise ValueError(f"Block {current_hash} not found in the chain.")
            block = self.blocks[current_hash]
            chain.append(block)
            current_hash = block.get_prev_block_hash()

        return chain


"""
Importing this file should NOT execute code. It should only create definitions for the objects above.
Write any tests you have in a different file.
You may add additional methods, classes and files but be sure no to change the signatures of methods
included in this template.
"""
