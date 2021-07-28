def func(
        product_id: str,
        price: int,
        cost: int,
        review_score: float,
        product_name_length: int,
        product_description_length: int,
        product_photos_qty: int,
        product_weight_g: int,
        product_length_cm: int,
        product_height_cm: int,
        product_width_cm: int
):
    def blackbox(submission_product_id: str, submission_price: int) -> int:
        return int(1 / submission_price + review_score)

    return blackbox
