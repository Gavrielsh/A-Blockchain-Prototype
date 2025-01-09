import hashlib
import secrets

from .utils import *
from .block import Block
from .transaction import Transaction
from typing import Set, Optional, List

class Node:
    def __init__(self) -> None:
        """
        Initializes the node with an empty blockchain, mempool, and no connections.
        """
        self.blockchain: List[Block] = []
        self.mempool: List[Transaction] = []
        self.utxo: List[Transaction] = []
        self.private_key, self.public_key = gen_keys()
        self.unspent_transaction: List[Transaction] = []
        self.pending_transaction: List[Transaction] = []
        self.connected_nodes: Set['Node'] = set()
        self.latest_block_hash: BlockHash = GENESIS_BLOCK_PREV  # Initialize to the genesis block hash



    def connect(self, other: 'Node') -> None:
        """Connects this node to another node for block and transaction updates.
        Connections are bidirectional, so the other node is connected to this one as well.
        Raises an exception if asked to connect to itself.
        The connection itself does not trigger updates about the mempool,
        but nodes instantly notify of their latest block to each other (see notify_of_block)"""
        if not isinstance(other, Node):
            raise TypeError("Expected a Node instance to connect.")

        if other.get_address() == self.get_address():
            raise ValueError("Cannot connect a node to itself.")

        if other not in self.connected_nodes:
            self.connected_nodes.add(other)
            other.connected_nodes.add(self)
            other.notify_of_block(self.get_latest_hash(), self)
        if self not in other.connected_nodes:
            other.connected_nodes.add(self)
            self.connected_nodes.add(other)
            self.notify_of_block(other.get_latest_hash(), other)

    def disconnect_from(self, other: 'Node') -> None:
        """Disconnects this node from the other node. If the two were not connected, then nothing happens"""
        if not isinstance(other, Node):
            raise TypeError("Expected a Node instance to disconnect.")

        if other in self.connected_nodes:
            self.connected_nodes.remove(other)
            other.connected_nodes.discard(self)

    def get_connections(self) -> Set['Node']:
        return self.connected_nodes

    def add_transaction_to_mempool(self, transaction: Transaction) -> bool:
        """
        Attempts to add a transaction to the node's mempool. Performs validation before adding.

        Returns:
            bool: True if the transaction is successfully added, False otherwise.
        """
        # check if the transaction is valid and has an output
        if not transaction or not transaction.input:
            return False

        # Validate input transaction exists in UTXO
        source_transaction = next(
            (tx for tx in self.utxo if tx.get_txid() == transaction.input), None
        )
        if not source_transaction:
            return False

        # Check for conflicting transactions already in the mempool
        if any(tx.input == transaction.input for tx in self.mempool):
            return False

        # Ensure the transaction is valid
        if not self._is_valid_transaction(transaction, source_transaction):
            return False


        # Add the transaction to the mempool
        self.mempool.append(transaction)

        # Propagate the transaction to connected nodes
        for node in self.connected_nodes:
            if node != self:
                node.add_transaction_to_mempool(transaction)


        return True

    def notify_of_block(self, block_hash: BlockHash, sender: 'Node') -> None:
        curr_block_hash = block_hash
        unknown_blocks = []

        # Fetch unknown blocks
        while not any(block.get_block_hash() == curr_block_hash for block in self.blockchain):
            try:
                block = sender.get_block(curr_block_hash)
                unknown_blocks.insert(0, block)
                curr_block_hash = block.get_prev_block_hash()
                if curr_block_hash == GENESIS_BLOCK_PREV:
                    break
            except ValueError:
                print(f"Block with hash {curr_block_hash} not found in sender.")
                if not unknown_blocks:
                    print("No valid blocks received from sender.")
                    return
                break

        if not unknown_blocks:
            print("No unknown blocks to process.")
            return

        # Validate blocks
        valid_blocks = []
        for block in unknown_blocks:
            if self._is_valid_block(block):
                valid_blocks.append(block)
            else:
                print(f"Block {block.get_block_hash().hex()} is invalid.")
                break

        if not valid_blocks:
            return

        # Rollback to split point
        current_hash = self.latest_block_hash
        split_point = valid_blocks[0].get_prev_block_hash()

        original_blockchain = self.blockchain.copy()
        original_utxo = self.utxo.copy()
        original_mempool = self.mempool.copy()
        original_latest_hash = self.latest_block_hash

        try:
            while current_hash != split_point:
                if not self.blockchain:
                    raise ValueError("Blockchain is empty; cannot rollback.")

                last_block = self.blockchain.pop()
                for tx in last_block.get_transactions():
                    self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.get_txid()]

                    if tx.input and any(utxo_tx.get_txid() == tx.input for utxo_tx in self.utxo):
                        self.mempool.append(tx)

                current_hash = last_block.get_prev_block_hash()

            # Apply valid blocks
            for block in valid_blocks:
                self.blockchain.append(block)
                for tx in block.get_transactions():
                    if tx.input:
                        self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.input]
                    self.utxo.append(tx)

                self.mempool = [mempool_tx for mempool_tx in self.mempool if
                                any(utxo_tx.get_txid() == mempool_tx.input for utxo_tx in self.utxo)]

            self.latest_block_hash = valid_blocks[-1].get_block_hash()

        except Exception as e:
            print(f"Error during notify_of_block: {str(e)}. Restoring original state.")
            self.blockchain = original_blockchain
            self.utxo = original_utxo
            self.mempool = original_mempool
            self.latest_block_hash = original_latest_hash

    def _is_valid_block(self, block: Block) -> bool:
        # Verify block hash
        if block.get_block_hash() != self._calculate_block_hash(block):
            return False

        # Track spent inputs within block
        spent_inputs = set()
        reward_count = 0

        for tx in block.get_transactions():
            if tx.input is None:
                reward_count += 1
                if reward_count > 1:
                    return False
            else:
                # Verify input exists in UTXO
                input_tx = next((utxo for utxo in self.utxo if utxo.get_txid() == tx.input), None)
                if not input_tx:
                    return False

                # Check for double-spending
                if tx.input in spent_inputs:
                    return False
                spent_inputs.add(tx.input)

                # Verify signature
                if not verify(tx.input + tx.output, tx.signature, input_tx.output):
                    return False

        return reward_count == 1

    def _calculate_block_hash(self, block: Block) -> BlockHash:
        return BlockHash(hashlib.sha256(
            block.get_prev_block_hash() +
            b''.join(tx.get_txid() for tx in block.get_transactions())
        ).digest())
    def _is_valid_transaction(self, tx: Transaction, input_tx: Optional[Transaction]) -> bool:
        """
        Verifies the validity of a transaction using its input transaction.
        """
        if input_tx is None:
            return False

        # Verify the signature matches the input and output
        expected_data = (tx.input or b'') + tx.output
        if not verify(expected_data, tx.signature, input_tx.output):
            print(f"Invalid transaction signature for tx: {tx.get_txid()}")
            return False

        return True

    def _reorganize_chain(self, new_tip: BlockHash) -> None:
        split_point = self._find_split_point(self.latest_block_hash, new_tip)

        # Rollback current chain
        current = self.latest_block_hash
        while current != split_point:
            block = self.get_block(current)
            # Remove transactions from UTXO
            for tx in block.get_transactions():
                if tx in self.utxo:
                    self.utxo.remove(tx)
                # Restore spent transactions
                if tx.input:
                    input_tx = next((utxo for utxo in self.utxo if utxo.get_txid() == tx.input), None)
                    if input_tx:
                        self.utxo.append(input_tx)
            current = block.get_prev_block_hash()

        # Apply new chain
        current = new_tip
        while current != split_point:
            block = self.get_block(current)
            self._update_utxo(block.get_transactions())
            current = block.get_prev_block_hash()

        self.latest_block_hash = new_tip

    def _find_split_point(self, hash1: BlockHash, hash2: BlockHash) -> BlockHash:
        seen_hashes = set()

        while hash1 or hash2:
            if hash1 in seen_hashes:
                return hash1
            if hash2 in seen_hashes:
                return hash2

            if hash1 is not None:
                seen_hashes.add(hash1)
                hash1 = self.blockchain[hash1].get_prev_block_hash() if hash1 in self.blockchain else None
            if hash2 is not None:
                seen_hashes.add(hash2)
                hash2 = self.blockchain[hash2].get_prev_block_hash() if hash2 in self.blockchain else None

        return GENESIS_BLOCK_PREV

    def mine_block(self) -> BlockHash:
        """"
        This function allows the node to create a single block.
        - The block should contain BLOCK_SIZE transactions (unless there aren't enough in the mempool).
        Of these,
        BLOCK_SIZE-1 transactions come from the mempool and one addtional transaction will be included that creates
        money and adds it to the address of this miner.
        - Money creation transactions have None as their input, and instead of a signature, contain 48 random bytes.
        - If a new block is created, all connections of this node are notified by calling their notify_of_block() method.
        The method returns the new block hash (or None if there was no block)
        """
        transactions: List[Transaction] = []

        # Create the coinbase transaction
        reward_transaction = Transaction(
            output=self.get_address(),
            tx_input=None,
            signature=Signature(secrets.token_bytes(64))
        )
        transactions.append(reward_transaction)

        # Add transactions from the mempool
        transactions.extend(self.get_mempool()[:BLOCK_SIZE - 1])

        # Create the new block
        new_block = Block(
            prev_block_hash=self.get_latest_hash(),
            transactions=transactions
        )
        self.blockchain.append(new_block)

        # Update UTXO and mempool
        self._update_utxo(transactions)
        self._manage_mempool(transactions)

        # when updating the UTxO with new txs in the new block, remove the txs that were the input:
        for tx in transactions:
            if tx.input:
                self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.input]

        # Update the latest block hash
        self.latest_block_hash = new_block.get_block_hash()

        # Notify connected nodes
        for node in self.connected_nodes:
            node.notify_of_block(new_block.get_block_hash(), self)

        return new_block.get_block_hash()

    def get_block(self, block_hash: BlockHash) -> Block:
        for block in self.blockchain:
            if block.get_block_hash() == block_hash:
                return block
        raise ValueError(f"Block with hash {block_hash} does not exist.")

    def get_latest_hash(self) -> BlockHash:
        if hasattr(self, 'latest_block_hash') and self.latest_block_hash is not None:
            return self.latest_block_hash
        return GENESIS_BLOCK_PREV if len(self.blockchain) == 0 else self.blockchain[-1].get_block_hash()

    def get_mempool(self) -> List[Transaction]:
        return self.mempool

    def create_transaction(self, target: PublicKey) -> Optional[Transaction]:
        """
        Creates a transaction from the node's UTXO to a specified target if possible.
        Ensures that the UTXO is not already spent in the mempool.

        Args:
            target (PublicKey): The address to which the transaction will be sent.

        Returns:
            Optional[Transaction]: The created transaction, or None if no valid UTXO is available.
        """
        # Step 1: Search for an available UTXO where the output matches the node's address
        for tx in self.utxo:
            if tx.output == self.get_address():  # Ensure the UTXO belongs to this node
                # Step 2: Check if the UTXO is already used in a pending transaction in the mempool
                if not any(mempool_tx.input == tx.get_txid() for mempool_tx in self.mempool):
                    # Step 3: Create a new transaction
                    txid = tx.get_txid()
                    private_key = self.private_key
                    signature = sign((txid or b'') + target, private_key)
                    new_transaction = Transaction(
                        output=target,
                        tx_input=txid,
                        signature=signature
                    )

                    # Step 4: Add the transaction to the mempool
                    if self.add_transaction_to_mempool(new_transaction):
                        return new_transaction

        # No valid UTXO found
        return None

    def clear_mempool(self) -> None:
        """
        Clears the mempool of this node. All transactions waiting to be entered into the next block are gone.
        Updates the unspent_transaction and pending_transaction lists accordingly.
        """
        self.mempool.clear()
        self.pending_transaction.clear()
        self.unspent_transaction.clear()

        # Rebuild unspent_transaction list based on current UTXO
        for tx in self.get_utxo():
            if tx.output == self.get_address():
                self.unspent_transaction.append(tx)

    def get_balance(self) -> int:
        balance = 0
        for tx in self.utxo:
            if tx.output == self.public_key:
                balance += 1
        return balance

    def get_address(self) -> PublicKey:
        return self.public_key

    def _update_utxo(self, transactions: List[Transaction]) -> None:
        """
        Updates the UTXO set based on the given transactions.
        """
        for tx in transactions:
            if tx.input:
                self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.input]
            self.utxo.append(tx)

    def get_utxo(self) -> List[Transaction]:
        return self.utxo.copy()

    def _manage_mempool(self, transactions: List[Transaction]) -> None:
        """
        Removes the given transactions from the mempool.
        """
        self.mempool = [tx for tx in self.mempool if tx not in transactions]

    def _get_chain_length(self, block_hash: BlockHash) -> int:
        length = 0
        current_hash = block_hash
        while current_hash in self.blockchain:
            block = self.blockchain[current_hash]
            current_hash = block.get_prev_block_hash()
            length += 1
        return length
