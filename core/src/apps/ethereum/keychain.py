from trezor import wire
from trezor.messages import EthereumSignTxEIP1559

from apps.common import paths
from apps.common.keychain import get_keychain

from . import CURVE, networks

if False:
    from typing import Callable, Iterable
    from typing_extensions import Protocol

    from protobuf import MessageType

    from trezor.messages import EthereumSignTx

    from apps.common.keychain import MsgOut, Handler, HandlerWithKeychain

    class MsgWithAddressN(MessageType, Protocol):
        address_n: paths.Bip32Path


# We believe Ethereum should use 44'/60'/a' for everything, because it is
# account-based, rather than UTXO-based. Unfortunately, lot of Ethereum
# tools (MEW, Metamask) do not use such scheme and set a = 0 and then
# iterate the address index i. For compatibility, we allow this scheme as well.

PATTERNS_ADDRESS = (paths.PATTERN_BIP44, paths.PATTERN_SEP5)


def _schemas_from_address_n(
    patterns: Iterable[str], address_n: paths.Bip32Path
) -> Iterable[paths.PathSchema]:
    if len(address_n) < 2:
        return ()

    slip44_hardened = address_n[1]
    if slip44_hardened not in networks.all_slip44_ids_hardened():
        return ()

    if not slip44_hardened & paths.HARDENED:
        return ()

    slip44_id = slip44_hardened - paths.HARDENED
    schemas = [paths.PathSchema.parse(pattern, slip44_id) for pattern in patterns]
    return [s.copy() for s in schemas]


def with_keychain_from_path(
    *patterns: str,
) -> Callable[
    [HandlerWithKeychain[MsgWithAddressN, MsgOut]], Handler[MsgWithAddressN, MsgOut]
]:
    def decorator(
        func: HandlerWithKeychain[MsgWithAddressN, MsgOut]
    ) -> Handler[MsgWithAddressN, MsgOut]:
        async def wrapper(ctx: wire.Context, msg: MsgWithAddressN) -> MsgOut:
            schemas = _schemas_from_address_n(patterns, msg.address_n)
            keychain = await get_keychain(ctx, CURVE, schemas)
            with keychain:
                return await func(ctx, msg, keychain)

        return wrapper

    return decorator


def _schemas_from_chain_id(msg: EthereumSignTx) -> Iterable[paths.PathSchema]:
    if msg.chain_id is None:
        return _schemas_from_address_n(PATTERNS_ADDRESS, msg.address_n)

    info = networks.by_chain_id(msg.chain_id)
    if info is None:
        # allow Ethereum or testnet paths for unknown networks
        slip44_id = (60, 1)
    elif not EthereumSignTxEIP1559.is_type_of(msg) and networks.is_wanchain(
        msg.chain_id, msg.tx_type
    ):
        slip44_id = (networks.SLIP44_WANCHAIN,)
    elif info.slip44 != 60 and info.slip44 != 1:
        # allow cross-signing with Ethereum unless it's testnet
        slip44_id = (info.slip44, 60)
    else:
        slip44_id = (info.slip44,)

    schemas = [
        paths.PathSchema.parse(pattern, slip44_id) for pattern in PATTERNS_ADDRESS
    ]
    return [s.copy() for s in schemas]


def with_keychain_from_chain_id(
    func: HandlerWithKeychain[EthereumSignTx, MsgOut]
) -> Handler[EthereumSignTx, MsgOut]:
    # this is only for SignTx, and only PATTERN_ADDRESS is allowed
    async def wrapper(ctx: wire.Context, msg: EthereumSignTx) -> MsgOut:
        schemas = _schemas_from_chain_id(msg)
        keychain = await get_keychain(ctx, CURVE, schemas)
        with keychain:
            return await func(ctx, msg, keychain)

    return wrapper
