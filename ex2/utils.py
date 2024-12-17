from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from typing import NewType, Tuple

# The following types are used to distinguish between bytes that are used as private keys, public keys and signature.
# This utilizes typechecking to ensure we won't be using them interchangeably.
PrivateKey = NewType('PrivateKey', bytes)
PublicKey = NewType('PublicKey', bytes)
Signature = NewType('Signature', bytes)

# We make similar type definitions for hashes:
BlockHash = NewType('BlockHash', bytes)  # This will be the hash of a block
TxID = NewType("TxID", bytes)  # this will be a hash of a transaction

# these are the bytes written as the prev_block_hash of the 1st block.
# (when a new wallet is created, it is updated up to this point)
GENESIS_BLOCK_PREV = BlockHash(b"Genesis")
# The maximal size of a block. Larger blocks are illegal. Do not change this value.
BLOCK_SIZE = 10


def sign(message: bytes, private_key: PrivateKey) -> Signature:
    """Signs the given message using the given private key"""
    pk = Ed25519PrivateKey.from_private_bytes(
        private_key)
    return Signature(pk.sign(message))


def verify(message: bytes, sig: Signature, pub_key: PublicKey) -> bool:
    """Verifies a signature for a given message using a public key. 
    Returns True is the signature matches, otherwise False"""
    pub_k = Ed25519PublicKey.from_public_bytes(
        pub_key)
    try:
        pub_k.verify(sig, message)
        return True
    except:
        return False


def gen_keys() -> Tuple[PrivateKey, PublicKey]:
    """generates a private key and a corresponding public key. 
    The keys are returned in byte format to allow them to be serialized easily."""
    private_key = Ed25519PrivateKey.generate()
    priv_key_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, encryption_algorithm=NoEncryption())
    pub_key_bytes = private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw)
    return PrivateKey(priv_key_bytes), PublicKey(pub_key_bytes)
