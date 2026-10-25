# Literature

Papers on football results and club share prices, for the report. Compiled 2026-10-09 from a web search, not a systematic review. Findings are as summarised by the abstracts or search results unless marked *read*; check against the paper before citing.

**When writing the report:** read every paper below in full, correct the summaries, complete the missing details, find the papers under "To find and check", and follow their reference lists for newer work. Move a paper out of "To find and check" once it is verified.

## How the project relates

| Our test | Prior work | Status |
|---|---|---|
| Day 0 reaction to the betting surprise | Scholtens & Peenstra 2009, Castellani et al. 2015, Godinho & Cerqueira 2018, Italian clubs 2026 | Known: replication |
| H1 drift over days +1 to +3 | Palomino et al. 2009 find overreaction to wins; Benkraiem et al. 2009 find bad news absorbed more slowly | Main contribution; Palomino et al. is the competing hypothesis |
| H2 good v bad news | Most studies: losses matter more; Geyer-Klingeberg et al. 2018 say this is partly publication bias | Known: replication |
| H3 competition type | Scholtens & Peenstra 2009 (European matches) | Partly known |
| E1 stakes | Godinho & Cerqueira 2018 (match importance weight) | Closest prior work, must cite |
| Backtest after costs | Benkraiem et al. 2009 mention trading profits; Kaplanski & Levy 2010 (World Cup, index level) | Not found at club level |
| Overlapping fixtures (distributed lags), stale prices (Dimson betas) | None found | New |

## Papers

### Palomino, Renneboog & Zhang (2009)
*Information salience, investor sentiment and stock returns: the case of British soccer betting.* Journal of Corporate Finance 15(3), 368–387.
UK listed clubs. Strong reaction to results (returns and volume), no reaction to the release of betting odds although they predict results well. Abnormal returns after wins look like sentiment driven overreaction, especially when the club was strongly expected to win. **Opposite of H1**: frame our drift test against it.
https://research.tilburguniversity.edu/en/publications/information-salience-investor-sentiment-and-stock-returns-the-cas/

### Godinho & Cerqueira (2018)
*The impact of expectations, match importance, and results in the stock prices of European football teams.* Journal of Sports Economics.
13 clubs, 6 countries, national league matches. Betting odds separate expected and unexpected results; a new match importance measure. With importance weighting the relation is significant for most teams. MGARCH. **Closest to E1.**
https://estudogeral.uc.pt/bitstream/10316/45584/1/JSE%20final.pdf

### Geyer-Klingeberg, Hang, Walter & Rathgeber (2018)
*Do stock markets react to soccer games? A meta-regression analysis.* Applied Economics 50(19), 2171–2189.
1,126 estimates from 37 studies. Wins: no significant effect (clubs or national teams). Losses: strong publication bias; national team losses about −5 bp after correction. Supports reporting a null with its minimum detectable effect.
https://ideas.repec.org/a/taf/applec/v50y2018i19p2171-2189.html

### Castellani, Pattitoni & Patuelli (2015)
*Abnormal returns of soccer teams: reassessing the informational value of betting odds.* Journal of Sports Economics.
Betting odds as expectations for club returns.
https://www.researchgate.net/publication/274507426_Abnormal_Returns_of_Soccer_Teams_Reassessing_the_Informational_Value_of_Betting_Odds

### Scholtens & Peenstra (2009)
*Scoring on the stock exchange? The effect of football matches on stock market returns: an event study.* Applied Economics.
Several European clubs, odds based expectations, national and European matches; losses matter more, European matches more.
https://www.researchgate.net/publication/227606262_Scoring_on_the_stock_exchange_The_effect_of_football_matches_on_stock_market_returns_An_event_study

### Benkraiem, Louhichi & Marques (2009)
*Market reaction to sporting results: the case of European listed football clubs.* Management Decision.
About +1% after wins on the first trading day, −1.4% after defeats, −0.6% after draws; abnormal volume from the day before the match; a pre-match return suggesting the market anticipates; mentions trading profits.
https://www.researchgate.net/publication/235282016_Market_reaction_to_sporting_results_The_case_of_European_listed_football_clubs

### The reaction of stock prices of Italian football teams to the surprise factor in match outcomes (2026)
Risk Governance & Control: Financial Markets & Institutions 16(1). Authors to check (University of Parma).
Juventus, Lazio, Roma, 2013/14 to 2018/19. Odds based surprise priced mostly at the next day's open; irregularities at the open corrected during the day. Asymmetries across clubs, rival results. Relevant to the open v close backtest variant.
https://doi.org/10.22495/rgcv16i1p14

### Stock price reactions to short-lived public information: the case of betting odds
Odds release and share prices. Authors and year to check.
https://www.researchgate.net/publication/4761765_Stock_price_reactions_to_short-lived_public_information_the_case_of_betting_odds

### Demir & Danis (2011)
*The effect of performance of soccer clubs on their stock prices: evidence from Turkey.* Emerging Markets Finance and Trade 47.
Besiktas, Fenerbahce, Galatasaray. For the Turkish clubs in the club table.
https://www.researchgate.net/publication/261967120_The_Effect_of_Performance_of_Soccer_Clubs_on_Their_Stock_Prices_Evidence_from_Turkey

### How betting market surprises affect the abnormal returns of football clubs (thesis)
Linnaeus University. Student thesis on the same question; useful for references, not as a main citation.
https://lnu.diva-portal.org/smash/get/diva2:2083138/FULLTEXT01.pdf

## To find and check

Not verified in the 2026-10-09 search, from memory:

- Edmans, García & Norli (2007), *Sports sentiment and stock returns*, Journal of Finance: national team losses and index returns. The standard sentiment reference.
- Bernile & Lyandres (2011), *Understanding investor sentiment: the case of soccer*, Financial Management: European clubs, odds based, pre-match optimism.
- Bell, Brooks, Matthews & Sutcliffe (2012), *Over the moon or sick as a parrot? The effects of football results on a club's share price*, Applied Economics: UK clubs.
- Renneboog & Vanbrabant (2000), share price reactions of LSE and AIM clubs.
- Stadtmann (2006), *Frequent news and pure signals: the case of a publicly traded football club*, Scottish Journal of Political Economy: Borussia Dortmund.
- Kaplanski & Levy (2010), *Exploitable predictable irrationality: the FIFA World Cup effect*, Journal of Banking & Finance: a trading strategy on sports sentiment.
- Brown & Hartzell (2001), *Market reaction to public information: the atypical case of the Boston Celtics*, Journal of Financial Economics.
- Method references for Step 4: Dimson (1979) beta, Corwin & Schultz (2012) spread estimator, Driscoll & Kraay (1998), Holm (1979).
