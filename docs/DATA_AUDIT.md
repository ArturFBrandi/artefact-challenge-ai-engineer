# Data audit

Findings from profiling `data/*.csv` and `data/políticas_da_loja.pdf`. The provided files are never
edited: every decision below lives in code or in `config/`.

Dates are relative to the default clock, Wednesday 2026-03-25 10:00 (Campo Grande).

## Volumes

| Table | Rows | Notes |
|---|---:|---|
| products | 65 | ids 81–145. No duplicates or missing values; all `specs` parse as JSON |
| categories | 9 | Categories 6, 7 and 8 have no products |
| customers | 50 | Fictional. Five cities, 24 in Campo Grande |
| orders | 20 | No orphans. Newest order is dated 2026-03-22 |
| order_items | 22 | All reference existing products |
| promotions | 25 | Only 4 are active |

## Catalog findings

| Finding | Decision |
|---|---|
| The manual claims 300+ instruments in categories that include wind and orchestral strings; the data has 65 products and none in those categories | The catalog is the only authority for what is sold. "Saxophone" gets an honest "not in the catalog" |
| #96 is `active` with stock 0 | Reported as temporarily unavailable, with alternatives |
| #136 is `discontinued` with stock 13 | Status beats quantity: not for sale |
| #130 is `coming_soon` with stock 2, yet appears on orders 3 and 14 | Status beats quantity: not for sale yet. History is left as is |
| Five products have "7 Cordas" in the name while string sets are not sold | Accessory handling is the model's reading of intent, not a keyword filter |

## Promotion findings

| Finding | Decision |
|---|---|
| `is_active` is the only validity signal; there are no dates | It is the authority |
| Products 93, 96 and 99 have several promotions, all inactive | Never shown |
| Takamine GD20 (#95) has an inactive 12% promotion | Listed at R$ 2.199,00 |
| "Desconto Exclusivo" is active on 3 products and does not say who it is for | **Assumed public** |
| The manual describes Black Friday as store-wide; no such promotion is active | Described if asked, never promised |

## Order findings

| Finding | Decision |
|---|---|
| Order 3: total R$ 3.450,00, items add to R$ 3.498,00 | The stored total is the record. Logged by the loader |
| Order 20: total R$ 1.400,00, items add to R$ 1.488,00 | Same |
| Orders 9, 16 and 18 used installments below the §3.1 minimums | Not precedent: rules apply to new quotes |
| No actual delivery date exists | `estimated_delivery` is a proxy, disclosed to the customer. A human decides when a window depends on it |
| No purchase channel exists | The agent asks, because the 7-day right of regret only covers online purchases |
| Order 8 is `shipped`, 25 days past its estimate | Acknowledge the delay, give the tracking code, offer a handoff. No reason is invented |

## Customer findings

| Finding | Decision |
|---|---|
| Customers 11 and 43 share `bruno.martins@jmail.com` | E-mail alone never identifies anyone |
| Phones and e-mails are well formed | Compared after normalization |

## Manual extraction

* `pypdf` returns one word per line.
* PyMuPDF `get_text()` keeps readable text, so it is used here. Its `find_tables()` removes spaces
  from cells, so tables are read as text rows.
* Repeated headers, page footers and zero-width characters after bullets are stripped.
* Sections 5.2 and 9 cross page boundaries, so chunks follow numbered sections rather than pages.

## Questions for store management

| # | Question | Default used until answered |
|---:|---|---|
| 1 | The WhatsApp number is (67) 3341-4444 in §1.2 and (67) 3321-4500 in §7. Which is right? | §7, the section about that channel |
| 2 | The e-mail is `contato@emporiodamusica.com.br` on the cover and `contato@empóriodamusica.com.br` in §1.2. Which is right? | The unaccented form |
| 3 | The §3 table sets a R$ 100 installment minimum; §3.1 sets tiers of R$ 50, 80 and 100. Which applies? | §3.1, the more specific rule |
| 4 | §3.1 says "sem valor mínimo … (exceto abaixo de R$ 50,00)". Is R$ 50 the minimum for up to 3x? | Yes |
| 5 | §4.2 sends defects to the manufacturer after 30 days; §8.1 gives 90 days of legal warranty. Who handles days 31–90? | A human, and the agent explains both rules |
| 6 | Does free shipping apply to exactly R$ 500,00? §5.1 says "above" and "below" only | The agent says it is undefined and hands off |
| 7 | Does the shipping threshold use the price before or after discounts? | After |
| 8 | When does the 7-day preference exchange in §4.3 start? | On receipt |
| 9 | Who qualifies for "Desconto Exclusivo"? | Everyone |
| 10 | Which municipalities are in the metro region? | Only Campo Grande is treated as metro |
| 11 | Which partner stores should be suggested for accessories (§7.1)? | None are named, so none are suggested |
| 12 | How is an order cancelled before delivery? No procedure is stated | Handed off |
