// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20QEReserve {
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

interface ISolvencyQE {
    function excessReserve() external view returns (uint256);
    function economicSolvencyBps() external view returns (uint256);
    function liquidityCoverageBps() external view returns (uint256);
    function gasCoverageBps() external view returns (uint256);
    function reservePolicyRatioBps() external view returns (uint256);
    function mode() external view returns (uint8);
}

interface ILedgerQE {
    function recordInternalTransfer(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address from,
        address to
    ) external returns (uint256);
}

interface IBoundaryQE {
    function isSystemAddress(address account) external view returns (bool);
}

/// @notice QE is implemented strictly as a reserve reclassification. It can
/// allocate only a bounded fraction of genuine excess reserves to productive
/// system buckets. It has no mint, buyback, operations or dividend path.
contract BackedReserveQE {
    uint256 public constant BPS = 10_000;
    uint256 public constant WINDOW = 30 days;

    enum Bucket {
        LIQUIDITY,
        BRIDGE,
        INSURANCE,
        PRODUCTIVE_YIELD
    }

    address public admin;
    mapping(address => bool) public operator;
    IERC20QEReserve public immutable reserveAsset;
    ISolvencyQE public immutable solvency;
    ILedgerQE public immutable ledger;
    IBoundaryQE public immutable registry;

    mapping(Bucket => address) public destination;
    uint16 public qeFractionBps;
    uint256 public monthlyCap;
    uint256 public windowStartedAt;
    uint256 public usedInWindow;
    uint256 public totalAllocated;

    error Unauthorized();
    error InvalidConfiguration();
    error AllocationNotAllowed();
    error TransferFailed();

    event OperatorSet(address indexed account, bool allowed);
    event DestinationSet(Bucket indexed bucket, address indexed destination);
    event QEPolicySet(uint16 fractionBps, uint256 monthlyCap);
    event ReserveReclassified(
        bytes32 indexed sourceId,
        Bucket indexed bucket,
        uint256 amount,
        address indexed destination
    );

    constructor(
        address admin_,
        IERC20QEReserve reserveAsset_,
        ISolvencyQE solvency_,
        ILedgerQE ledger_,
        IBoundaryQE registry_,
        uint16 qeFractionBps_,
        uint256 monthlyCap_
    ) {
        if (
            admin_ == address(0) || address(reserveAsset_) == address(0)
                || address(solvency_) == address(0) || address(ledger_) == address(0)
                || address(registry_) == address(0) || qeFractionBps_ > 2_000
        ) revert InvalidConfiguration();
        admin = admin_;
        operator[admin_] = true;
        reserveAsset = reserveAsset_;
        solvency = solvency_;
        ledger = ledger_;
        registry = registry_;
        qeFractionBps = qeFractionBps_;
        monthlyCap = monthlyCap_;
        windowStartedAt = block.timestamp;
        emit OperatorSet(admin_, true);
        emit QEPolicySet(qeFractionBps_, monthlyCap_);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyOperator() {
        if (!operator[msg.sender]) revert Unauthorized();
        _;
    }

    function setOperator(address account, bool allowed) external onlyAdmin {
        if (account == address(0)) revert InvalidConfiguration();
        operator[account] = allowed;
        emit OperatorSet(account, allowed);
    }

    function setDestination(Bucket bucket, address account) external onlyAdmin {
        if (account == address(0) || !registry.isSystemAddress(account)) {
            revert InvalidConfiguration();
        }
        destination[bucket] = account;
        emit DestinationSet(bucket, account);
    }

    function setPolicy(uint16 fractionBps, uint256 cap) external onlyAdmin {
        if (fractionBps > 2_000) revert InvalidConfiguration();
        qeFractionBps = fractionBps;
        monthlyCap = cap;
        emit QEPolicySet(fractionBps, cap);
    }

    function availableQE() public view returns (uint256) {
        uint256 excess = solvency.excessReserve();
        uint256 fractionBound = excess * qeFractionBps / BPS;
        uint256 used = block.timestamp >= windowStartedAt + WINDOW ? 0 : usedInWindow;
        uint256 capBound = monthlyCap > used ? monthlyCap - used : 0;
        uint256 balance = reserveAsset.balanceOf(address(this));
        uint256 allowed = fractionBound < capBound ? fractionBound : capBound;
        return allowed < balance ? allowed : balance;
    }

    function allocate(Bucket bucket, uint256 amount, bytes32 sourceId) external onlyOperator {
        _rollWindow();
        address target = destination[bucket];
        if (target == address(0) || amount == 0 || amount > availableQE()) {
            revert AllocationNotAllowed();
        }
        // 2 = NORMAL in SolvencyController.Mode. QE is disabled in RECOVERY,
        // DEFENSIVE, PAUSED, DIVIDEND and EMERGENCY.
        if (
            solvency.mode() != 2 || solvency.economicSolvencyBps() < 12_000
                || solvency.liquidityCoverageBps() < 12_000 || solvency.gasCoverageBps() < 12_000
                || solvency.reservePolicyRatioBps() < 7_000
        ) revert AllocationNotAllowed();

        usedInWindow += amount;
        totalAllocated += amount;
        if (!reserveAsset.transfer(target, amount)) revert TransferFailed();
        ledger.recordInternalTransfer(sourceId, address(reserveAsset), amount, address(this), target);
        emit ReserveReclassified(sourceId, bucket, amount, target);
    }

    function _rollWindow() private {
        if (block.timestamp >= windowStartedAt + WINDOW) {
            windowStartedAt = block.timestamp;
            usedInWindow = 0;
        }
    }
}
