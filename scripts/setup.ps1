# Lab 01 setup: create a wallet, mine 101 blocks, report the state.
#
# Read this script before running it. It is deliberately short and does nothing
# you could not type by hand; the point is that you should be able to.

$ErrorActionPreference = "Stop"

$WALLET = "lab01"

function Invoke-Bitcoin {
    param([Parameter(ValueFromRemainingArguments = $true)] $Args)
    docker compose exec -T bitcoind bitcoin-cli @Args
}

function Invoke-Wallet {
    param([Parameter(ValueFromRemainingArguments = $true)] $Args)
    docker compose exec -T bitcoind bitcoin-cli "-rpcwallet=$WALLET" @Args
}

Write-Host "== Waiting for bitcoind RPC ==" -ForegroundColor Cyan
$ready = $false
foreach ($i in 1..30) {
    try {
        Invoke-Bitcoin getblockchaininfo | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $ready) {
    throw "bitcoind did not become ready. Check: docker compose logs bitcoind"
}

Write-Host "== Creating / loading wallet '$WALLET' ==" -ForegroundColor Cyan
# createwallet fails if the wallet already exists, so try loadwallet first.
# A descriptor wallet (the modern default) is used; legacy wallets are deprecated.
try {
    Invoke-Bitcoin loadwallet $WALLET | Out-Null
    Write-Host "   loaded existing wallet"
} catch {
    Invoke-Bitcoin createwallet $WALLET | Out-Null
    Write-Host "   created new descriptor wallet"
}

Write-Host "== Generating mining address ==" -ForegroundColor Cyan
$ADDR = (Invoke-Wallet getnewaddress "mining").Trim()
Write-Host "   $ADDR"

Write-Host "== Mining 101 blocks ==" -ForegroundColor Cyan
# 101 and not 1: a coinbase output requires 100 further blocks before it is
# spendable (COINBASE_MATURITY). Mining 101 matures exactly the first reward.
Invoke-Wallet -generate 101 | Out-Null

$height  = (Invoke-Bitcoin getblockcount).Trim()
$balance = (Invoke-Wallet getbalance).Trim()
$mature  = (Invoke-Wallet listunspent 100 | ConvertFrom-Json).Count
$all     = (Invoke-Wallet listunspent 0   | ConvertFrom-Json).Count

Write-Host ""
Write-Host "== State ==" -ForegroundColor Green
Write-Host "   block height        : $height"
Write-Host "   spendable balance   : $balance BTC"
Write-Host "   mature UTXOs        : $mature"
Write-Host "   UTXOs incl. immature: $all"
Write-Host ""
Write-Host "Note the asymmetry: 101 coinbase outputs exist, exactly one is spendable."
Write-Host "Explain that in your report."
Write-Host ""
Write-Host "Next: docker compose exec bitcoind bitcoin-cli -rpcwallet=$WALLET listunspent 100"
