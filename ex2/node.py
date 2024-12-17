import hashlib
import secrets

from .utils import *
from .block import Block
from .transaction import Transaction
from typing import Set, Optional, List

class Node:
    def __init__(self) -> None:
        self.private_key, self.public_key = gen_keys()
        self.mempool: List[Transaction] = []  # רשימת טרנזקציות מחכות לבלוק
        self.connections: Set[Node] = set()  # צמתים מחוברים
        self.blocks: dict[BlockHash, Block] = {}  # בלוקים ידועים
        self.latest_block_hash: BlockHash = GENESIS_BLOCK_PREV  # בלוק אחרון בשרשרת
        self.utxo: List[Transaction] = []  # רשימת יציאות לא משומשות

    def connect(self, other: 'Node') -> None:
        if other == self:
            raise ValueError("Node cannot connect to itself.")
        self.connections.add(other)
        other.connections.add(self)
        other.notify_of_block(self.latest_block_hash, self)

    def disconnect_from(self, other: 'Node') -> None:
        self.connections.discard(other)
        other.connections.discard(self)

    def get_connections(self) -> Set['Node']:
        return self.connections

    def add_transaction_to_mempool(self, transaction: Transaction) -> bool:
        if not verify(transaction.get_txid(), transaction.signature, transaction.output):
            return False

        if transaction.input and transaction.input not in [tx.get_txid() for tx in self.utxo]:
            return False

        # עדכון UTXO
        self.utxo = [tx for tx in self.utxo if tx.get_txid() != transaction.input]

        self.mempool.append(transaction)

        for node in self.connections:
            node.add_transaction_to_mempool(transaction)

        return True

    def notify_of_block(self, block_hash: BlockHash, sender: 'Node') -> None:
        """
        Processes a block notification from a connected node.
        Stops updating if any block or transaction is invalid.
        """
        if block_hash in self.blocks:
            print(f"[DEBUG] Block {block_hash} already known")
            return  # אם הבלוק כבר ידוע, אין צורך להמשיך

        # בקשת הבלוק
        try:
            new_block = sender.get_block(block_hash)
        except ValueError:
            print(f"[DEBUG] Block {block_hash} not found in sender")
            return  # אם הבלוק אינו זמין, מתעלמים

        # בדיקת תקינות הבלוק
        if not self._is_valid_block(new_block):
            print(f"[DEBUG] Block {block_hash} is invalid")
            return  # בלוק לא חוקי, עוצרים את העדכון

        # שמירת הבלוק החדש
        print(f"[DEBUG] Adding block {block_hash} to chain")
        self.blocks[block_hash] = new_block

        # בדיקה אם יש בלוקים חסרים בשרשרת
        prev_block_hash = new_block.get_prev_block_hash()
        while prev_block_hash not in self.blocks and prev_block_hash != GENESIS_BLOCK_PREV:
            try:
                prev_block = sender.get_block(prev_block_hash)
            except ValueError:
                print(f"[DEBUG] Block {prev_block_hash} not found")
                return  # אם הבלוק הקודם אינו זמין, מתעלמים

            if not self._is_valid_block(prev_block):
                print(f"[DEBUG] Block {prev_block_hash} is invalid")
                return  # אם הבלוק הקודם אינו חוקי, עוצרים את העדכון

            print(f"[DEBUG] Adding missing block {prev_block_hash}")
            self.blocks[prev_block_hash] = prev_block
            prev_block_hash = prev_block.get_prev_block_hash()

        # עדכון latest_block_hash אם השרשרת החדשה ארוכה יותר
        current_chain_length = self._get_chain_length(self.latest_block_hash)
        new_chain_length = self._get_chain_length(block_hash)
        if new_chain_length > current_chain_length:
            print(f"[DEBUG] Updating latest_block_hash to {block_hash}")
            self._reorganize_chain(block_hash)
        else:
            print(f"[DEBUG] Chain not updated, current length {current_chain_length}, new length {new_chain_length}")

    def _is_valid_block(self, block: Block) -> bool:
        expected_hash = BlockHash(hashlib.sha256(
            block.get_prev_block_hash() + b''.join(tx.get_txid() for tx in block.get_transactions())
        ).digest())

        if block.get_block_hash() != expected_hash:
            return False

        if len(block.get_transactions()) > BLOCK_SIZE:
            return False

        reward_tx_count = sum(1 for tx in block.get_transactions() if tx.input is None)
        if reward_tx_count > 1:
            return False

        seen_txids = set()
        for tx in block.get_transactions():
            if tx.get_txid() in seen_txids:
                return False  # טרנזקציות כפולות בתוך אותו בלוק
            seen_txids.add(tx.get_txid())
            if tx.input and not verify(tx.get_txid(), tx.signature, tx.output):
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
        """
        Reorganizes the chain to follow the branch ending at new_tip.
        Rolls back to the split point and applies the new chain from new_tip.
        """

        # 1. Find the split point between the current chain and the new branch
        split_point = self._find_split_point(self.latest_block_hash, new_tip)

        # 2. Roll back the chain to the split point, undoing blocks beyond it
        self._rollback_to_split_point(split_point)

        # 3. Prepare a set of TXIDs currently in the UTXO for faster lookup
        new_utxo_txids = {tx.get_txid() for tx in self.utxo}

        # 4. Start processing the new branch from the tip backwards until the split point
        current_hash = new_tip
        while current_hash != split_point:
            # 4.1 Fetch the block corresponding to the current hash
            block = self.blocks[current_hash]

            # 4.2 Validate the block before applying its transactions
            if not self._is_valid_block(block):
                print(f"[DEBUG] Invalid block {current_hash}. Stopping reorganization.")
                return  # Stop processing if the block is invalid

            # 4.3 Process each transaction in the block
            for tx in block.get_transactions():
                # 4.3.1 If the transaction spends an input already in the UTXO, remove it
                if tx.input and tx.input in {utxo_tx.get_txid() for utxo_tx in self.utxo}:
                    self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.input]

                # 4.3.2 If the transaction's TXID is not already in the UTXO, add it
                if tx.get_txid() not in {utxo_tx.get_txid() for utxo_tx in self.utxo}:
                    self.utxo.append(tx)

            # 4.4 Move to the previous block in the new branch
            current_hash = block.get_prev_block_hash()

        # 5. Update the latest block hash to the tip of the new branch
        self.latest_block_hash = new_tip

    def _rollback_to_split_point(self, split_point: BlockHash) -> None:
        current_hash = self.latest_block_hash

        while current_hash != split_point:
            if current_hash not in self.blocks:
                raise ValueError(f"Block {current_hash} is missing in the chain.")

            block = self.blocks[current_hash]
            for tx in block.get_transactions():
                if tx.get_txid() in [utxo_tx.get_txid() for utxo_tx in self.utxo]:
                    self.utxo = [utxo_tx for utxo_tx in self.utxo if utxo_tx.get_txid() != tx.get_txid()]
                if tx.input:  # החזרת טרנזקציות עם input לממפול
                    self.mempool.append(tx)

            current_hash = block.get_prev_block_hash()

    def _find_split_point(self, hash1: BlockHash, hash2: BlockHash) -> BlockHash:
        """
        Finds the common ancestor (split point) between two chains.
        """
        seen_hashes = set()

        # הליכה אחורה משני ה-hashes עד שמוצאים נקודת פיצול
        while hash1 or hash2:
            if hash1 in seen_hashes:
                return hash1
            if hash2 in seen_hashes:
                return hash2

            if hash1 is not None:
                seen_hashes.add(hash1)
                hash1 = self.blocks[hash1].get_prev_block_hash() if hash1 in self.blocks else None

            if hash2 is not None:
                seen_hashes.add(hash2)
                hash2 = self.blocks[hash2].get_prev_block_hash() if hash2 in self.blocks else None

        # אם לא נמצא פיצול, חוזרים ל-GENESIS_BLOCK_PREV
        return GENESIS_BLOCK_PREV

    def mine_block(self) -> Optional[BlockHash]:
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

        # עדכון UTXO ללא כפילויות
        existing_txids = {tx.get_txid() for tx in self.utxo}
        for tx in transactions:
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
        # חיפוש UTXO מתאים שלא נמצא בשימוש ב-mempool
        for tx in self.utxo:
            if not any(mempool_tx.input == tx.get_txid() for mempool_tx in self.mempool):
                # יצירת טרנזקציה חדשה
                txid = tx.get_txid()
                private_key = self.private_key  # נניח שיש לנו private_key בצומת
                signature = sign(txid, private_key)

                new_transaction = Transaction(
                    output=target,
                    tx_input=txid,
                    signature=signature
                )

                # הוספה ל-mempool
                self.add_transaction_to_mempool(new_transaction)

                return new_transaction

        # אם אין מטבעות זמינים, מחזירים None
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
                balance += 1  # כל טרנזקציה ב-UTXO שמכוונת לצומת מוסיפה מטבע אחד
        return balance

    def get_address(self) -> PublicKey:
        """
        Returns the public address of this node (its public key).
        """
        return self.public_key


"""
Importing this file should NOT execute code. It should only create definitions for the objects above.
Write any tests you have in a different file.
You may add additional methods, classes and files but be sure no to change the signatures of methods
included in this template.
"""
