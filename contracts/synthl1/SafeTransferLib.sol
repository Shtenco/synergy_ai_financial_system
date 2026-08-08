// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library SafeTransferLib {
    error TokenCallFailed();

    function safeTransfer(address token, address to, uint256 amount) internal {
        (bool ok, bytes memory ret) =
            token.call(abi.encodeWithSignature("transfer(address,uint256)", to, amount));
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TokenCallFailed();
    }

    function safeTransferFrom(address token, address from, address to, uint256 amount) internal {
        (bool ok, bytes memory ret) =
            token.call(abi.encodeWithSignature("transferFrom(address,address,uint256)", from, to, amount));
        if (!ok || (ret.length != 0 && !abi.decode(ret, (bool)))) revert TokenCallFailed();
    }

    function forceApprove(address token, address spender, uint256 amount) internal {
        (bool ok0, bytes memory ret0) =
            token.call(abi.encodeWithSignature("approve(address,uint256)", spender, 0));
        if (!ok0 || (ret0.length != 0 && !abi.decode(ret0, (bool)))) revert TokenCallFailed();
        if (amount != 0) {
            (bool ok1, bytes memory ret1) =
                token.call(abi.encodeWithSignature("approve(address,uint256)", spender, amount));
            if (!ok1 || (ret1.length != 0 && !abi.decode(ret1, (bool)))) revert TokenCallFailed();
        }
    }
}
