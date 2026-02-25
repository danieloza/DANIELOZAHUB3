def calculate_no_show_losses(cancelled_visits: list):
    """
    Calculates total money lost due to non-arrivals.
    """
    total_loss = sum(float(v.get('price', 0)) for v in cancelled_visits if v.get('reason') == 'no_show')
    return f"Strata w tym miesiącu: {total_loss:.2f} zł"
