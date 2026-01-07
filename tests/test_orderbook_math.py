from castle.strategy.orderbook_math import best_prices, mid_prob

def test_implied_ask_mid():
    yes = [[10, 1], [20, 1]]
    no = [[70, 1]]
    bp = best_prices(yes, no)
    assert bp.best_yes_bid == 20
    assert bp.best_yes_ask == 30  # implied from best NO bid=70 => YES ask=30
    assert abs(mid_prob(bp.best_yes_bid, bp.best_yes_ask) - 0.25) < 1e-9
