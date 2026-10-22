# Phase-0 cited facts (retrieved 2026-10-04) — seed for the curated registry. Facts only as the sources state them.

## On-chain identity (Ethereum, eth_call 2-of-N, block 26119871)
- BUIDL 0x7712c34205737192402172409a8F7ccef8aA2AEc — name "BlackRock USD Institutional Digital Liquidity Fund", decimals 6
- USYC 0x136471a34f6ef19fE571EFFC1CA711fdb8E49f2b — "US Yield Coin", decimals 6 (most supply on BSC: 0x8D0f…)
- OUSG 0x1B19C19393e2d034D8Ff31ff34c81252FcBbee92 — "Ondo Short-Term U.S. Government Bond Fund", decimals 18
- USDY 0x96F6eF951840721AdBF46Ac996b59E0235CB985C — "Ondo U.S. Dollar Yield", decimals 18

## NAV oracles (on-chain)
- USYC Oracle 0x74f2199AEb743f68f05943e5715A33EaF2b61f53 — Chainlink-interface latestRoundData(); decimals 18; round 525
  answer 1.139002815 updatedAt 2026-10-02T12:31:59Z; updates once per business day ~9am ET (usyc.docs.hashnote.com/overview/token-price)
- USDY USDYOracleWrapper 0x87b126e5518b6a1Bb8465779b4607C45C643DF90 — getPrice() 1.14843046; getPriceData() returns (price, timestamp);
  underlying 0xA0219AA5B31e65Bc920B5b6DFb8EdF0988121De0 same value
- OUSG OndoOracle 0x9Cad45a8BF0Ed41Ff33074449B357C7a1fAb4094 — getAssetPrice(OUSG) 116.767284; no timestamp getter (use block time)
- BUIDL — no on-chain NAV documented on Ethereum; RedStone off-chain gateway BUIDL_DAILY_INTEREST_ACCRUAL (9.339e-5)
- Circularity: DeFiLlama yield-server adapters derive APY from these same oracles/feeds ⇒ ONE origin per fund.

## DeFiLlama pools — correct chain joins
- BUIDL Ethereum pool b2b1d98f… (3.467%); factory joined 590d770e… = BUIDL Solana (3.778%) — WRONG
- OUSG Ethereum pool 7436db9b… (3.43%); factory joined 36e8a552… = XRPL — WRONG
- USYC Ethereum pool 448a64ff…; factory joined 7c0a89c7… = BSC — WRONG
- USDY Ethereum pool ac61ee82… — correct
(full uuids: re-resolve from yields.llama.fi/pools by chain=Ethereum AND underlyingTokens containing the contract)

## Counterparty roles (state per ADR-562 rules)
- BUIDL issuer/legal: BlackRock USD Institutional Digital Liquidity Fund Ltd., CIK 0002013810, BVI, 3(c)(7); Form D/A
  https://www.sec.gov/Archives/edgar/data/2013810/000201381026000002/primary_doc.xml (2026-07-27) — regulatory filing.
  Min investment accepted $100,000 (Form D).
- BUIDL custodian: "Bank of New York Mellon serves as BUIDL's cash and securities custodian"; transfer agent Securitize, LLC —
  https://www.prnewswire.com/news-releases/blackrock-usd-institutional-digital-liquidity-fund-buidl-tokenized-by-securitize-surpasses-1b-in-aum-302401480.html
  (issuer/tokeniser press release ⇒ IDENTIFIED). Redemption mechanism: UNKNOWN (repo's USDC-via-Circle not verified). Fees: no official figure.
- USYC issuer: "Circle International Bermuda Limited, regulated by Bermuda Monetary Authority" — https://usyc.docs.hashnote.com/
  custodian/prime broker: Marex; bank: Customers Bank; MPC: Fireblocks — usyc.docs.hashnote.com/overview/service-providers.md
  redemption: Teller USDC 0xeE35F963…30e6, 24/7 T+0 — overview/smart-contracts, introduction
  legal: interest in SDYF (Hashnote International Short Duration Yield Fund, Cayman mutual fund) — overview/product-structuring.md;
  administrator NAV Consulting; auditor Cohen and Company — same docs. Eligibility: non-US institutions, $100k min.
  fees: performance 10% of yield, subscription 4 bps, redemption 3 bps — overview/fees.md. API /api/price-reports has daily fee field.
- USDY issuer: "a tokenized note formerly issued by Ondo USDY LLC" (docs USDY basics) vs eligibility page "Ondo Global Markets (BVI) Limited" — CONFLICT
  redemption: Ondo, USD wire to non-US accounts; USDY_InstantManager 0xa42613C2…1f15 (docs.ondo.finance/addresses)
  collateral/verification agent: Ankura Trust (Ondo blog 2023-08-03); custodian: UNKNOWN; fees: "minus a small spread", size undisclosed
- OUSG issuer: Ondo (docs OUSG overview); legal: Ondo I LP, Delaware, CIK 0001957431, 3(c)(7), min $5,000 — Form D/A
  https://www.sec.gov/Archives/edgar/data/1957431/000195743126000001/primary_doc.xml (2026-01-20) — link OUSG↔Ondo I LP INFERRED (not stated by Ondo)
  redemption: OUSG_InstantManager 0x93358db7…643a; instant atomic, else next business day; min $5k instant / $50k non-instant (docs OUSG redeeming)
  custodian: UNKNOWN; administrator NAV Consulting; fees: 0.15% mgmt waived until 2027-01-01, expenses capped 0.15% (docs OUSG fees)

## Funding venues (public, keyless)
- Binance fapi premiumIndex (markPrice, indexPrice, lastFundingRate, nextFundingTime, time), fundingRate (fundingTime, fundingRate, markPrice),
  fundingInfo, depth (E/T); spot bookTicker/depth have no timestamps; exchangeInfo serverTime is CDN-stale — not a freshness source.
  Legal: Binance ADGM — Nest Exchange / Nest Clearing and Custody Limited (Recognised Clearing House) / Nest Trading — https://www.binance.com/en/terms
  Fees: FAQ example only (not verified).
- Bybit v5: tickers (markPrice, indexPrice, fundingRate, time), funding/history (fundingRateTimestamp), instruments-info, risk-limit (maintenanceMargin). Legal UNKNOWN. Fees not verified.
- OKX: funding-rate (premium, settFundingRate, settState, ts), mark-price, index-tickers, books (ts), instruments (ctVal), position-tiers (mmr). Legal UNKNOWN (jurisdiction routing). Fees not verified.
- KuCoin futures: contracts/{sym} (takerFeeRate 0.0006 = OFFICIAL_API fee, markPrice, indexPrice, maintainMargin), funding-rates (timepoint), level2/depth20.
  Legal: terms name no entity, Turks and Caicos law — https://www.kucoin.com/legal/terms-of-use
- Hyperliquid /info: metaAndAssetCtxs (markPx, oraclePx, premium; no time), fundingHistory (hourly, time, premium), l2Book (time).
  Fees: perps 0.045% taker / spot 0.070% — https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees ; no native BTC/ETH spot.
