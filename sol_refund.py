from termcolor import cprint, colored
from pprint import pprint
import base58
import json
import time

from solana.rpc.api import Client
from solana.rpc.commitment import Commitment
from solana.rpc.types import TokenAccountOpts
from solana.rpc.types import TxOpts
from solana.transaction import Transaction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import close_account
from spl.token.instructions import CloseAccountParams
import dontshare as private_keys

print("Starting the Solana token account refund tool...")

# 설정 - 원본과 동일
BATCH_SIZE = 4  # 배치 처리만 추가
rpc_endpoint = private_keys.ankr_key
wallet_address = "4wgfCBf2WwLSRKLef9iW7JXZ2AfkxUxGM4XcKpHm3Sin"
wallet_private_key = private_keys.sol_key

print(f"Using RPC URL: {rpc_endpoint}")
print(f"Wallet address: {wallet_address}")

# Convert wallet address and key to pubkey and keypair
wallet_public_key = Pubkey.from_string(wallet_address)  # 최신 API로만 변경

if wallet_private_key:
    wallet_keypair = Keypair.from_base58_string(wallet_private_key)
    print("Wallet keypair created successfully")
else:
    wallet_keypair = None
    print("Warning: No wallet key provided, wallet_keypair is None")

# Print wallet public key and keypair public key for debugging
print(f"wallet_public_key      : {wallet_public_key}")
print(f"wallet_keypair pubkey  : {wallet_keypair.pubkey()}")

# Check if the wallet_keypair's public key matches the wallet_public_key
if wallet_public_key != wallet_keypair.pubkey():
    print("Error: The provided wallet_private_key does not correspond to the wallet_address.")
    print("Please ensure that the private key (wallet_private_key) matches the wallet address (wallet_address).")
    exit(1)
else:
    print("Wallet key and address match. Proceeding...")

# 클라이언트 한번만 생성 (개선점)
solana_client = Client(rpc_endpoint, commitment=Commitment("confirmed"), timeout=30, blockhash_cache=True)
print("Solana client initialized")


def close_all_empty_token_accounts(owner_public_key):
    print("\nStarting close_all_empty_token_accounts function...")
    sol_refunded_this_account = 0
    total_sol_refunded = 0
    
    print("Fetching token accounts...")
    token_accounts = solana_client.get_token_accounts_by_owner_json_parsed(
        owner=owner_public_key,
        opts=TokenAccountOpts(program_id=TOKEN_PROGRAM_ID),
        commitment=None
    )
    account_count = len(token_accounts.value)
    expected_sol_reclaim = 0.00203928
    expected_total_refund = account_count * expected_sol_reclaim
    print(f"Estimating : {:21.8f} SOL refund on {} token accounts".format(expected_total_refund, account_count))
    print('')
    
    if not token_accounts.value:
        print("No token accounts found.")
        return
    
    # 배치 처리를 위한 리스트
    accounts_to_close = []
    
    for token_account in token_accounts.value:
        print("Processing account:")
        pprint(token_account)
        print('')
        
        token_account_pubkey = token_account.pubkey
        token_mint_address = token_account.account.data.parsed['info']['mint']
        token_owner = token_account.account.data.parsed['info']['owner']
        token_balance = token_account.account.data.parsed['info']['tokenAmount']['uiAmount']
        token_decimals = token_account.account.data.parsed['info']['tokenAmount']['decimals']
        token_rent_epoch = token_account.account.rent_epoch
        account_lamports = token_account.account.lamports
        
        print('Token account details:')
        print('token_owner         : {} ({})'.format(token_owner, type(token_owner)))
        print('token mint address  : {} ({})'.format(token_mint_address, type(token_mint_address)))
        print('token_account_pubkey: {} ({})'.format(token_account_pubkey, type(token_account_pubkey)))
        print('token_balance       : {} ({})'.format(token_balance, type(token_balance)))
        print('token_decimals      : {} ({})'.format(token_decimals, type(token_decimals)))
        print('token_rent_epoch    : {} ({})'.format(token_rent_epoch, type(token_rent_epoch)))
        
        token_mint_pubkey = Pubkey.from_string(token_mint_address)  # 최신 API
        program_id_pubkey = TOKEN_PROGRAM_ID
        
        print(f"Account             : {token_account_pubkey}")
        print(f"Token Mint          : {token_mint_address}")
        print(f"Token Balance       : {token_balance}")
        print(f"Lamports (SOL)      : {account_lamports / 1e9}")
        
        # Decision to close the account
        if token_balance > 0:
            print_warning("NOT CLOSING account - balance is greater than 0")
        elif token_balance == 0:
            print_success("CLOSING account - balance is 0")
            accounts_to_close.append({
                'pubkey': token_account_pubkey,
                'lamports': account_lamports,
                'mint': token_mint_address
            })
    
    # 배치 처리 (개선점)
    if accounts_to_close and wallet_keypair:
        for i in range(0, len(accounts_to_close), BATCH_SIZE):
            batch = accounts_to_close[i:i + BATCH_SIZE]
            
            # 트랜잭션 생성
            transaction = Transaction()
            batch_sol_refunded = 0
            
            for account in batch:
                close_account_instruction = close_account(
                    CloseAccountParams(
                        account=account['pubkey'],
                        dest=owner_public_key,
                        owner=owner_public_key,
                        program_id=program_id_pubkey
                    )
                )
                transaction.add(close_account_instruction)
                batch_sol_refunded += account['lamports'] / 1e9
            
            print(f"\nBatch transaction created with {len(batch)} accounts, waiting 3 seconds before sending...")
            time.sleep(3)
            
            try:
                # 최신 blockhash 가져오기
                recent_blockhash = solana_client.get_latest_blockhash()
                transaction.recent_blockhash = recent_blockhash.value.blockhash
                
                # Send the transaction
                print("Sending batch transaction...")
                response = solana_client.send_transaction(
                    transaction,
                    wallet_keypair,
                    opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed")
                )
                
                total_sol_refunded += batch_sol_refunded
                print(f"Batch transaction successful: {response}")
                print("refund_amt : {:>14.8f}, tot_refund_amt : {:14.8f}".format(batch_sol_refunded, total_sol_refunded))
                
                for account in batch:
                    print(f"Transaction successful, closed account {account['pubkey']} {account['mint']}")
                
            except Exception as e:
                print(f"Exception occurred while closing batch: {e}")
                raise
            
            if i + BATCH_SIZE < len(accounts_to_close):
                print("Waiting 10 seconds before processing next batch...")
                time.sleep(10)


def close_specific_token_account(owner_public_key, token_mint_address):
    print("\nStarting close_specific_token_account function...")
    
    # 새 클라이언트 대신 기존 클라이언트 사용 (개선점)
    print("Using existing Solana client")
    
    token_mint_pubkey = Pubkey.from_string(token_mint_address)  # 최신 API
    program_id_pubkey = TOKEN_PROGRAM_ID
    
    print("Waiting 1 second before fetching account...")
    time.sleep(1)
    
    print(f"Fetching token account for address: {token_mint_address}")
    token_account = solana_client.get_token_accounts_by_owner_json_parsed(
        owner_public_key,
        TokenAccountOpts(token_mint_pubkey)
    )
    
    print("Token account data:")
    print(token_account.value[0].account.data)
    
    token_account_pubkey = token_account.value[0].pubkey
    token_mint_address = token_account.value[0].account.data.parsed['info']['mint']
    is_native_token = token_account.value[0].account.data.parsed['info']['isNative']
    token_owner = token_account.value[0].account.data.parsed['info']['owner']
    token_balance = token_account.value[0].account.data.parsed['info']['tokenAmount']['uiAmount']
    token_decimals = token_account.value[0].account.data.parsed['info']['tokenAmount']['decimals']
    token_rent_epoch = token_account.value[0].account.rent_epoch
    account_lamports = token_account.value[0].account.lamports
    
    print('Token account details:')
    print('token_owner         : {} ({})'.format(token_owner, type(token_owner)))
    print('token_mint_address  : {} ({})'.format(token_mint_address, type(token_mint_address)))
    print('is_native_token     : {} ({})'.format(is_native_token, type(is_native_token)))
    print('token_account_pubkey: {} ({})'.format(token_account_pubkey, type(token_account_pubkey)))
    print('token_balance       : {} ({})'.format(token_balance, type(token_balance)))
    print('token_decimals      : {} ({})'.format(token_decimals, type(token_decimals)))
    print('token_rent_epoch    : {} ({})'.format(token_rent_epoch, type(token_rent_epoch)))
    
    print(f"Account             : {token_account_pubkey}")
    print(f"Token Mint          : {token_mint_address}")
    print(f"Token Balance       : {token_balance}")
    print(f"Lamports (SOL)      : {account_lamports / 1e9}")
    
    # Close the account
    print_success("CLOSING account...")
    
    sol_refunded = account_lamports / 1e9
    print("refund_amt          : {:>14.8f}".format(sol_refunded))
    if wallet_keypair:
        print("Creating close account instruction...")
        close_account_instruction = close_account(
            CloseAccountParams(
                account=token_account_pubkey,
                dest=owner_public_key,
                owner=owner_public_key,
                program_id=program_id_pubkey
            )
        )
        
        transaction = Transaction()
        transaction.add(close_account_instruction)
        
        # 최신 blockhash 가져오기
        recent_blockhash = solana_client.get_latest_blockhash()
        transaction.recent_blockhash = recent_blockhash.value.blockhash
        
        print("Transaction created, waiting 1 second before sending...")
        time.sleep(1)
        try:
            print("Sending transaction...")
            response = solana_client.send_transaction(
                transaction,
                wallet_keypair,
                opts=TxOpts(skip_preflight=False, preflight_commitment="confirmed")
            )
            print(f"Transaction successful, closed account {token_account_pubkey} {token_mint_address}: {response}")
        except Exception as e:
            print(f"Exception occurred while closing account {token_account_pubkey}: {e}")
            raise
    
    print("close_specific_token_account function completed")


# Note: This function prints a message with white text on green background
def print_success(message, print_to_console=True):
    if print_to_console:
        cprint(message, 'white', 'on_green')
    else:
        return colored(message, 'white', 'on_green')


# Note: This function prints a message with white text on red background
def print_warning(message, print_to_console=True):
    if print_to_console:
        cprint(message, 'white', 'on_red')
    else:
        return colored(message, 'white', 'on_red')


print("Calling close_all_empty_token_accounts function...")
close_all_empty_token_accounts(wallet_public_key)

print("Script execution completed.")