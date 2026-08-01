// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20V15 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

contract V15ExternalRevenueEngine {
    IERC20V15 public immutable settlementToken;
    address public immutable treasury;
    mapping(address => bool) public approvedSolver;
    mapping(address => uint256) public solverBid;
    address[] public bidders;
    address public bestSolver;
    uint256 public bestBid;
    bool public auctionSettled;
    mapping(bytes32 => bool) public usedQuote;

    event SolverBid(address indexed solver, uint256 amount);
    event AuctionSettled(address indexed winner, uint256 amount);
    event SignedRfqFilled(bytes32 indexed quoteHash, address indexed maker, address indexed taker,
        address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut);

    constructor(address settlementToken_, address treasury_, address[] memory solvers_) {
        require(settlementToken_ != address(0) && treasury_ != address(0), "zero address");
        settlementToken = IERC20V15(settlementToken_);
        treasury = treasury_;
        for (uint256 i = 0; i < solvers_.length; i++) {
            require(solvers_[i] != address(0), "zero solver");
            approvedSolver[solvers_[i]] = true;
        }
    }

    function bid(uint256 amount) external {
        require(!auctionSettled, "settled");
        require(approvedSolver[msg.sender], "not solver");
        require(amount > 0 && solverBid[msg.sender] == 0, "invalid bid");
        _safeTransferFrom(settlementToken, msg.sender, address(this), amount);
        solverBid[msg.sender] = amount;
        bidders.push(msg.sender);
        if (amount > bestBid) {
            bestBid = amount;
            bestSolver = msg.sender;
        }
        emit SolverBid(msg.sender, amount);
    }

    function settleAuction() external {
        require(msg.sender == treasury, "not treasury");
        require(!auctionSettled && bestSolver != address(0), "not ready");
        auctionSettled = true;
        _safeTransfer(settlementToken, treasury, bestBid);
        for (uint256 i = 0; i < bidders.length; i++) {
            address bidder = bidders[i];
            if (bidder != bestSolver) {
                _safeTransfer(settlementToken, bidder, solverBid[bidder]);
            }
        }
        emit AuctionSettled(bestSolver, bestBid);
    }

    function quoteHash(
        address maker,
        address taker,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 nonce,
        uint256 deadline
    ) public view returns (bytes32) {
        return keccak256(abi.encode(
            address(this), block.chainid, maker, taker, tokenIn, tokenOut,
            amountIn, amountOut, nonce, deadline
        ));
    }

    function fillSignedQuote(
        address maker,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 nonce,
        uint256 deadline,
        bytes calldata signature
    ) external returns (bytes32 hash) {
        require(block.timestamp <= deadline, "expired");
        hash = quoteHash(maker, msg.sender, tokenIn, tokenOut, amountIn, amountOut, nonce, deadline);
        require(!usedQuote[hash], "used quote");
        bytes32 digest = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", hash));
        require(_recover(digest, signature) == maker, "bad signature");
        usedQuote[hash] = true;
        _safeTransferFrom(IERC20V15(tokenIn), msg.sender, maker, amountIn);
        _safeTransferFrom(IERC20V15(tokenOut), maker, msg.sender, amountOut);
        emit SignedRfqFilled(hash, maker, msg.sender, tokenIn, tokenOut, amountIn, amountOut);
    }

    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address signer) {
        require(signature.length == 65, "bad sig length");
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (v < 27) v += 27;
        require(v == 27 || v == 28, "bad v");
        signer = ecrecover(digest, v, r, s);
        require(signer != address(0), "bad signer");
    }

    function _safeTransfer(IERC20V15 token, address to, uint256 amount) private {
        (bool ok, bytes memory data) = address(token).call(
            abi.encodeWithSelector(token.transfer.selector, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "transfer failed");
    }

    function _safeTransferFrom(IERC20V15 token, address from, address to, uint256 amount) private {
        (bool ok, bytes memory data) = address(token).call(
            abi.encodeWithSelector(token.transferFrom.selector, from, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "transferFrom failed");
    }
}
