"""Pre-requisite checks module for all trading strategies.

This module provides a generic framework for validating stocks before strategy evaluation.
All checks are mandatory (AND logic) - if any check fails, the stock is rejected.

Usage:
    checker = PrerequisiteChecker(config)
    result = checker.check(symbol, current_data)
    if not result.passed:
        return {'error': result.error_message, 'failed_checks': result.failed_checks}
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass
class PrerequisiteResult:
    """Result of prerequisite checks."""
    passed: bool
    failed_checks: List[str]
    error_message: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            'passed': self.passed,
            'failed_checks': self.failed_checks,
            'error_message': self.error_message,
            'details': self.details or {}
        }


@dataclass
class PrerequisiteConfig:
    """Configuration for prerequisite checks."""
    # RVOL checks
    min_rvol: float = 1.0
    rvol_enabled: bool = True

    # Future checks (placeholder for extensibility)
    min_liquidity_cr: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    allowed_sectors: Optional[List[str]] = None
    blocked_symbols: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, data: dict) -> PrerequisiteConfig:
        """Create config from dictionary (from database or API)."""
        return cls(
            min_rvol=float(data.get('min_rvol', 1.0)),
            rvol_enabled=bool(data.get('rvol_enabled', True)),
            min_liquidity_cr=data.get('min_liquidity_cr'),
            min_price=data.get('min_price'),
            max_price=data.get('max_price'),
            allowed_sectors=data.get('allowed_sectors'),
            blocked_symbols=data.get('blocked_symbols'),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            'min_rvol': self.min_rvol,
            'rvol_enabled': self.rvol_enabled,
            'min_liquidity_cr': self.min_liquidity_cr,
            'min_price': self.min_price,
            'max_price': self.max_price,
            'allowed_sectors': self.allowed_sectors,
            'blocked_symbols': self.blocked_symbols,
        }


class PrerequisiteChecker:
    """Validates stocks against mandatory pre-requisite checks before strategy evaluation."""

    def __init__(self, config: PrerequisiteConfig):
        """Initialize checker with configuration.

        Args:
            config: PrerequisiteConfig with thresholds and rules
        """
        self.config = config

    def check(self, symbol: str, data: Dict[str, Any]) -> PrerequisiteResult:
        """Run all prerequisite checks on a stock.

        All checks are mandatory (AND logic). If any fails, evaluation stops.

        Args:
            symbol: Stock symbol (e.g., "NSE:RELIANCE-EQ")
            data: Dictionary with stock data:
                - rvol: float (relative volume)
                - price: float (current price)
                - liquidity_cr: float (liquidity in crores)
                - sector: str (optional)

        Returns:
            PrerequisiteResult with pass/fail status and details
        """
        failed_checks = []
        details = {}

        # Check 1: RVOL (Relative Volume)
        if self.config.rvol_enabled:
            rvol_result = self._check_rvol(symbol, data.get('rvol'))
            if not rvol_result['passed']:
                failed_checks.append('RVOL')
                details['rvol'] = rvol_result

        # Check 2: Liquidity (future - currently disabled)
        if self.config.min_liquidity_cr is not None:
            liquidity_result = self._check_liquidity(data.get('liquidity_cr'))
            if not liquidity_result['passed']:
                failed_checks.append('Liquidity')
                details['liquidity'] = liquidity_result

        # Check 3: Price Range (future - currently disabled)
        if self.config.min_price or self.config.max_price:
            price_result = self._check_price_range(data.get('price'))
            if not price_result['passed']:
                failed_checks.append('Price Range')
                details['price'] = price_result

        # Check 4: Blocked Symbols (future - currently disabled)
        if self.config.blocked_symbols:
            if symbol in self.config.blocked_symbols:
                failed_checks.append('Blocked Symbol')
                details['blocked'] = {
                    'passed': False,
                    'reason': f'{symbol} is in blocked list',
                    'symbol': symbol
                }

        # Check 5: Allowed Sectors (future - currently disabled)
        if self.config.allowed_sectors:
            sector_result = self._check_sector(data.get('sector'))
            if not sector_result['passed']:
                failed_checks.append('Sector')
                details['sector'] = sector_result

        # Result
        passed = len(failed_checks) == 0
        error_message = None

        if not passed:
            error_message = f"Pre-requisite checks failed: {', '.join(failed_checks)}"

        return PrerequisiteResult(
            passed=passed,
            failed_checks=failed_checks,
            error_message=error_message,
            details=details
        )

    def _check_rvol(self, symbol: str, rvol: Optional[float]) -> dict:
        """Check if RVOL meets minimum threshold.

        Args:
            symbol: Stock symbol
            rvol: Relative volume (can be None if not available)

        Returns:
            dict with passed status and details
        """
        if rvol is None:
            return {
                'passed': False,
                'reason': 'RVOL data not available',
                'threshold': self.config.min_rvol,
                'actual': None
            }

        passed = rvol >= self.config.min_rvol

        return {
            'passed': passed,
            'reason': f'RVOL {rvol:.2f} < {self.config.min_rvol}' if not passed else f'RVOL {rvol:.2f} ✓',
            'threshold': self.config.min_rvol,
            'actual': rvol
        }

    def _check_liquidity(self, liquidity_cr: Optional[float]) -> dict:
        """Check if liquidity meets minimum threshold.

        Args:
            liquidity_cr: Liquidity in crores

        Returns:
            dict with passed status and details
        """
        if liquidity_cr is None:
            return {
                'passed': False,
                'reason': 'Liquidity data not available',
                'threshold': self.config.min_liquidity_cr,
                'actual': None
            }

        passed = liquidity_cr >= self.config.min_liquidity_cr

        return {
            'passed': passed,
            'reason': f'Liquidity ₹{liquidity_cr:.1f}Cr < ₹{self.config.min_liquidity_cr}Cr' if not passed else f'Liquidity ₹{liquidity_cr:.1f}Cr ✓',
            'threshold': self.config.min_liquidity_cr,
            'actual': liquidity_cr
        }

    def _check_price_range(self, price: Optional[float]) -> dict:
        """Check if price is within allowed range.

        Args:
            price: Current stock price

        Returns:
            dict with passed status and details
        """
        if price is None:
            return {
                'passed': False,
                'reason': 'Price data not available',
                'min': self.config.min_price,
                'max': self.config.max_price,
                'actual': None
            }

        if self.config.min_price and price < self.config.min_price:
            return {
                'passed': False,
                'reason': f'Price ₹{price:.2f} < min ₹{self.config.min_price}',
                'min': self.config.min_price,
                'max': self.config.max_price,
                'actual': price
            }

        if self.config.max_price and price > self.config.max_price:
            return {
                'passed': False,
                'reason': f'Price ₹{price:.2f} > max ₹{self.config.max_price}',
                'min': self.config.min_price,
                'max': self.config.max_price,
                'actual': price
            }

        return {
            'passed': True,
            'reason': f'Price ₹{price:.2f} within range ✓',
            'min': self.config.min_price,
            'max': self.config.max_price,
            'actual': price
        }

    def _check_sector(self, sector: Optional[str]) -> dict:
        """Check if sector is in allowed list.

        Args:
            sector: Stock sector

        Returns:
            dict with passed status and details
        """
        if sector is None:
            return {
                'passed': False,
                'reason': 'Sector data not available',
                'allowed': self.config.allowed_sectors,
                'actual': None
            }

        passed = sector in self.config.allowed_sectors

        return {
            'passed': passed,
            'reason': f'Sector "{sector}" not in allowed list' if not passed else f'Sector "{sector}" ✓',
            'allowed': self.config.allowed_sectors,
            'actual': sector
        }

    def get_summary(self) -> str:
        """Get human-readable summary of active checks.

        Returns:
            String describing active prerequisite checks
        """
        checks = []

        if self.config.rvol_enabled:
            checks.append(f'RVOL ≥ {self.config.min_rvol}')

        if self.config.min_liquidity_cr:
            checks.append(f'Liquidity ≥ ₹{self.config.min_liquidity_cr}Cr')

        if self.config.min_price or self.config.max_price:
            if self.config.min_price and self.config.max_price:
                checks.append(f'Price: ₹{self.config.min_price}-{self.config.max_price}')
            elif self.config.min_price:
                checks.append(f'Price ≥ ₹{self.config.min_price}')
            elif self.config.max_price:
                checks.append(f'Price ≤ ₹{self.config.max_price}')

        if self.config.allowed_sectors:
            checks.append(f'Sectors: {", ".join(self.config.allowed_sectors)}')

        if self.config.blocked_symbols:
            checks.append(f'{len(self.config.blocked_symbols)} blocked symbols')

        if not checks:
            return "No active prerequisite checks"

        return "Active checks: " + " | ".join(checks)


# Convenience function for quick checks
def check_prerequisites(symbol: str, data: Dict[str, Any], config: PrerequisiteConfig) -> PrerequisiteResult:
    """Quick prerequisite check without creating a checker instance.

    Args:
        symbol: Stock symbol
        data: Stock data dictionary
        config: PrerequisiteConfig

    Returns:
        PrerequisiteResult
    """
    checker = PrerequisiteChecker(config)
    return checker.check(symbol, data)
