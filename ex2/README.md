# Blockchain Project: Node Implementation

### Authors
- **Gavriel Shalem**: 205461486  
- **Netanel Birahoz**: 311227888

### Overview
This project is a simplified blockchain implementation focusing on the core principles of decentralized transaction management, node synchronization, and data integrity. It is a coursework submission designed to illustrate our understanding of blockchain technology and Python programming.

---

## Project Features

### 1. **Blockchain and Nodes**
- **Block Structure**: Each block contains a reference to the previous block (hash) and a list of transactions.
- **Node Management**: Nodes interact with each other by sharing blocks and transactions to maintain consistency.

### 2. **Transactions**
- Transactions represent the transfer of coins and are cryptographically signed to ensure authenticity.
- Supports both coin creation (mining rewards) and coin transfers.

### 3. **Mempool Management**
- A mempool is used to store unconfirmed transactions.
- Transactions in the mempool are checked for validity, ensuring no double-spending occurs.

### 4. **Mining**
- Nodes can mine new blocks, which include transactions from the mempool.
- Mining creates a reward transaction, introducing new coins into the system.

### 5. **Node Synchronization**
- Nodes propagate new blocks and transactions to their neighbors.
- Chain reorganization is handled when a longer chain is discovered.

### 6. **Security**
- Transactions and blocks are validated to ensure:
  - Proper signatures.
  - Valid previous hashes.
  - Correct block sizes and contents.

---

## Implementation Details

### 1. **Key Classes**
#### `Block`
- Stores transactions and the hash of the previous block.
- Computes its hash based on its contents.

#### `Transaction`
- Represents coin transfers.
- Includes fields for inputs, outputs, and a digital signature.

#### `Node`
- Manages the blockchain, mempool, and UTXO (Unspent Transaction Outputs).
- Handles mining, transactions, and synchronization.

### 2. **Utilities**
- **Cryptography**: Used for signing and verifying transactions.
- **Hashing**: Ensures data integrity for blocks and transactions.

### 3. **Testing**
- Extensive unit tests are provided using `pytest`.
- Tests include scenarios for:
  - Mining blocks.
  - Validating transactions.
  - Chain reorganization.
  - Node synchronization.

---

## Instructions

### Prerequisites
- Install dependencies using `requirements.txt`:
  ```bash
  pip install -r requirements.txt
  ```

### Running the Tests
- Use `pytest` to execute the tests:
  ```bash
  pytest --cov=.
  ```
- Ensure all tests pass before final submission.

### Example Workflow
1. **Create Nodes**:
   ```python
   alice = Node()
   bob = Node()
   ```

2. **Connect Nodes**:
   ```python
   alice.connect(bob)
   ```

3. **Mine a Block**:
   ```python
   alice.mine_block()
   ```

4. **Send a Transaction**:
   ```python
   tx = alice.create_transaction(bob.get_address())
   ```

5. **Validate Chain**:
   ```python
   assert alice.get_latest_hash() == bob.get_latest_hash()
   ```

---

## Challenges and Learning Outcomes

### Challenges
- Implementing node synchronization efficiently.
- Handling edge cases in transaction validation and chain reorganization.

### Learning Outcomes
- Gained a deep understanding of blockchain principles.
- Learned how to use Python for cryptographic operations and data structures.
- Improved skills in testing and debugging complex systems.


