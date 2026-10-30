"""CHI (Coherent Hub Interface, Arm IHI 0050 Issue H) BFMs: configuration
and flit layouts, opcode tables, the link-layer models (L-Credits,
FLITPEND, LINKACTIVE, LCrdReturn), the transaction and cache models, and
the RN-F / HN-F / monitor BFMs with their factories."""

from .chi_cache_model import (
    LINE_BYTES,
    CacheLine,
    HomeDecision,
    HomePolicy,
    RNCache,
    SnoopFilter,
    SnoopResponse,
    line_addr,
)
from .chi_config import CONFIG_RULES, CHIConfig, CHIIssue, NodeType
from .chi_factories import create_chi_home, create_chi_monitor, create_chi_requester
from .chi_flits import (
    ALIASES,
    CHANNELS,
    LAYOUTS,
    CHIDatFlit,
    CHIFlit,
    CHIReqFlit,
    CHIRspFlit,
    CHISnpFlit,
    build_field_config,
    flit_class,
)
from .chi_hn import CHIHome, CHIHomeNode, HomeOptions
from .chi_link import (
    ACTIVATE,
    DEACTIVATE,
    LCRD_RETURN,
    RUN,
    STOP,
    LCreditRx,
    LCreditTx,
    LinkChecker,
    RxChannel,
    RxLink,
    TxChannel,
    TxLink,
    link_state,
)
from .chi_monitor import CHIMonitor
from .chi_opcodes import (
    CACHE_STATES,
    DIRTY_STATES,
    SC,
    SD,
    UC,
    UCE,
    UD,
    UDP,
    UNIQUE_STATES,
    AtomicOp,
    DatOpcode,
    FwdState,
    I,
    MemAttr,
    Order,
    ReqOpcode,
    Resp,
    RespErr,
    RspOpcode,
    Size,
    SnpOpcode,
    atomic_opcode,
    data_id,
    data_ids_for,
    data_window_lo,
    data_windows,
    opcode_name,
    req_opcode_name,
    resp_encode,
    resp_state,
)
from .chi_port import CHIPort
from .chi_rn import CHIRequestNode
from .chi_transaction import (
    REQ_CLASS,
    Action,
    CHITransaction,
    CompleterEntry,
    CompleterTracker,
    ReqClass,
    RequesterTracker,
    TxnIdPool,
    needs_compack,
    req_class,
    write_data_opcode,
)

__all__ = [
    'CHIConfig', 'CHIIssue', 'NodeType', 'CONFIG_RULES',
    'CHANNELS', 'LAYOUTS', 'ALIASES', 'CHIFlit', 'CHIReqFlit', 'CHIRspFlit', 'CHISnpFlit', 'CHIDatFlit',
    'build_field_config', 'flit_class',
    'ReqOpcode', 'RspOpcode', 'SnpOpcode', 'DatOpcode', 'AtomicOp', 'atomic_opcode', 'req_opcode_name',
    'opcode_name', 'Size', 'MemAttr', 'Order', 'RespErr', 'Resp', 'FwdState', 'resp_state', 'resp_encode',
    'I', 'UC', 'UCE', 'UD', 'UDP', 'SC', 'SD', 'CACHE_STATES', 'UNIQUE_STATES', 'DIRTY_STATES',
    'data_id', 'data_ids_for', 'data_window_lo', 'data_windows',
    'STOP', 'ACTIVATE', 'RUN', 'DEACTIVATE', 'LCRD_RETURN', 'link_state', 'LCreditTx', 'LCreditRx',
    'TxChannel', 'RxChannel', 'TxLink', 'RxLink', 'LinkChecker',
    'ReqClass', 'REQ_CLASS', 'req_class', 'needs_compack', 'write_data_opcode', 'Action', 'CHITransaction',
    'TxnIdPool', 'RequesterTracker', 'CompleterEntry', 'CompleterTracker',
    'LINE_BYTES', 'line_addr', 'CacheLine', 'RNCache', 'SnoopResponse', 'SnoopFilter', 'HomeDecision', 'HomePolicy',
    'CHIPort', 'CHIRequestNode', 'CHIHome', 'CHIHomeNode', 'HomeOptions', 'CHIMonitor',
    'create_chi_requester', 'create_chi_home', 'create_chi_monitor',
]
