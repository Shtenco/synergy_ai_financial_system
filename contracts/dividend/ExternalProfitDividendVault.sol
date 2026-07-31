// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20DividendAsset {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}

interface IBoundaryDividend {
    function isSystemAddress(address account) external view returns (bool);
}

interface ISolvencyDividend {
    function dividendableCapital() external view returns (uint256);
    function canPayDividend(uint256 amount) external view returns (bool);
    function economicSolvencyBps() external view returns (uint256);
    function liquidityCoverageBps() external view returns (uint256);
    function gasCoverageBps() external view returns (uint256);
    function reservePolicyRatioBps() external view returns (uint256);
}

interface ILedgerDividend {
    function recordDividend(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address systemPayer,
        address externalRecipient
    ) external returns (uint256);
    function realizedExternalPnL() external view returns (int256);
    function totalDividends() external view returns (uint256);
}

/// @notice Dividend vault that can distribute only ledger-proven realized
/// external profit and must preserve a local operating reserve plus all global
/// solvency, liquidity, gas and reserve-policy gates.
contract ExternalProfitDividendVault {
    uint256 public constant BPS = 10_000;

    address public admin;
    mapping(address => bool) public operator;
    IERC20DividendAsset public immutable reserveAsset;
    IBoundaryDividend public immutable registry;
    ISolvencyDividend public immutable solvency;
    ILedgerDividend public immutable ledger;

    uint256 public minimumLocalReserve;
    uint16 public payoutRateBps;

    error Unauthorized();
    error InvalidConfiguration();
    error DividendNotAllowed();
    error TransferFailed();

    event OperatorSet(address indexed account, bool allowed);
    event DividendPolicySet(uint256 minimumLocalReserve, uint16 payoutRateBps);
    event DividendPaid(address indexed recipient, uint256 amount, uint256 localReserveAfter);

    constructor(
        address admin_,
        IERC20DividendAsset reserveAsset_,
        IBoundaryDividend registry_,
        ISolvencyDividend solvency_,
        ILedgerDividend ledger_,
        uint256 minimumLocalReserve_,
        uint16 payoutRateBps_
    ) {
        if (
            admin_ == address(0) || address(reserveAsset_) == address(0)
                || address(registry_) == address(0) || address(solvency_) == address(0)
                || address(ledger_) == address(0) || payoutRateBps_ > BPS
        ) revert InvalidConfiguration();
        admin = admin_;
        operator[admin_] = true;
        reserveAsset = reserveAsset_;
        registry = registry_;
        solvency = solvency_;
        ledger = ledger_;
        minimumLocalReserve = minimumLocalReserve_;
        payoutRateBps = payoutRateBps_;
        emit OperatorSet(admin_, true);
        emit DividendPolicySet(minimumLocalReserve_, payoutRateBps_);
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

    function setPolicy(uint256 minimumLocalReserve_, uint16 payoutRateBps_) external onlyAdmin {
        if (payoutRateBps_ > BPS) revert InvalidConfiguration();
        minimumLocalReserve = minimumLocalReserve_;
        payoutRateBps = payoutRateBps_;
        emit DividendPolicySet(minimumLocalReserve_, payoutRateBps_);
    }

    function maximumDividend() public view returns (uint256) {
        uint256 balance = reserveAsset.balanceOf(address(this));
        uint256 localBound = balance > minimumLocalReserve ? balance - minimumLocalReserve : 0;
        uint256 globalBound = solvency.dividendableCapital();
        uint256 payoutBound = globalBound * payoutRateBps / BPS;
        return localBound < payoutBound ? localBound : payoutBound;
    }

    function payDividend(address recipient, uint256 requestedAmount, bytes32 sourceId)
        external
        onlyOperator
        returns (uint256 amount)
    {
        if (recipient == address(0) || registry.isSystemAddress(recipient)) revert DividendNotAllowed();
        uint256 maximum = maximumDividend();
        amount = requestedAmount == 0 || requestedAmount > maximum ? maximum : requestedAmount;
        if (
            amount == 0 || !solvency.canPayDividend(amount)
                || solvency.economicSolvencyBps() < 12_000 || solvency.liquidityCoverageBps() < 12_000
                || solvency.gasCoverageBps() < 12_000 || solvency.reservePolicyRatioBps() < 7_000
        ) revert DividendNotAllowed();

        int256 pnl = ledger.realizedExternalPnL();
        if (pnl <= 0 || ledger.totalDividends() + amount > uint256(pnl)) revert DividendNotAllowed();
        if (!reserveAsset.transfer(recipient, amount)) revert TransferFailed();
        ledger.recordDividend(sourceId, address(reserveAsset), amount, address(this), recipient);
        emit DividendPaid(recipient, amount, reserveAsset.balanceOf(address(this)));
    }
}
