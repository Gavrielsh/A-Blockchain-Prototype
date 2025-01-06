import hashlib
from datetime import time

from .utils import BlockHash  # ייבוא BlockHash
from .transaction import Transaction  # ייבוא Transaction
from typing import List  # עבור רשימות

class Block:
    def __init__(self, prev_block_hash: BlockHash, transactions: List[Transaction]) -> None:
        self.prev_block_hash = prev_block_hash
        self.transactions = transactions

    def get_block_hash(self) -> BlockHash:
        """
        Computes the hash of the block's data, including its transactions and the previous block's hash.
        """
        data = self.prev_block_hash + b''.join(tx.get_txid() for tx in self.transactions)
        return BlockHash(hashlib.sha256(data).digest())

    def get_transactions(self) -> List[Transaction]:
        """
        Returns the list of transactions in this block.
        """
        return self.transactions

    def get_prev_block_hash(self) -> BlockHash:
        """
        Returns the hash of the previous block.
        """
        return self.prev_block_hash