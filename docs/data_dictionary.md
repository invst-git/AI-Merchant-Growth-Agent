# Data Dictionary (Phase 1)

## UCI Online Retail II — done

Source: HuggingFace mirror of the UCI dataset (archive.ics.uci.edu's own
zip endpoint doesn't support resumable/ranged downloads from this
environment, so the file was pulled from
huggingface.co/datasets/michaelmallari/online-retail-ii instead, same
underlying data). Raw file: data/raw/uci/online-retail-ii.xlsx (two
sheets, Year 2009-2010 and Year 2010-2011). Processed table:
data/processed/uci_baskets.parquet.

Columns: Invoice (basket id, "C" prefix = cancellation, dropped),
StockCode, Description, Quantity, InvoiceDate, Price (GBP), Customer_ID,
Country, line_value (Quantity x Price, added during cleaning).

Actuals from this run: 1,067,371 raw rows, 805,549 after dropping
cancellations and rows with a missing Customer_ID or Description, 36,969
unique baskets, 5,878 unique customers, 4,631 unique products.

## dunnhumby Complete Journey — pending download

Source: Kaggle (frtgnn/dunnhumby-the-complete-journey) or dunnhumby's own
source-files portal. Needs Kaggle API credentials or a manual download —
see Phase 1 status in the project's memory / README for the open
question. Expected in data/raw/dunnhumby/, processed by
data_prep/preprocess_dunnhumby.py into data/processed/dunnhumby_baskets.parquet.

Key tables and fields (per the Buildathon research doc, to be confirmed
against the actual CSV headers once downloaded):
- transaction_data: household_key, BASKET_ID, DAY, PRODUCT_ID, QUANTITY,
  SALES_VALUE, STORE_ID, retail_disc, coupon_disc, coupon_match_disc.
  loyalty_price = (sales_value - (retail_disc + coupon_match_disc)) / quantity.
- product: PRODUCT_ID, DEPARTMENT, COMMODITY_DESC, SUB_COMMODITY_DESC,
  BRAND, manufacturer — the 3-level category hierarchy used for
  complement/substitute reasoning in Phase 2.
- hh_demographic: age, income, household size, home ownership, children
  (partial coverage).
- campaign_table / campaign_desc / coupon / coupon_redempt: marketing
  contact and redemption history, used as a weak treatment signal for
  the Phase 2 acceptance model.

## Olist Brazilian E-Commerce — pending download

Source: Kaggle (olistbr/brazilian-ecommerce), same credential
requirement as dunnhumby. Expected in data/raw/olist/, processed by
data_prep/preprocess_olist.py into data/processed/olist_baskets.parquet.

Key tables and fields:
- olist_orders_dataset: order id, status, timestamps.
- olist_order_items_dataset: order_id, product_id, seller_id, price,
  freight_value.
- olist_order_payments_dataset: payment_type, installments, payment_value.
- olist_products_dataset, olist_sellers_dataset,
  olist_order_reviews_dataset (review score),
  product_category_name_translation.

Note: most Olist orders are single-item, so this dataset is used for
marketplace/seller and payment-mix realism, not as a primary source of
cross-sell affinity signal (dunnhumby's grocery baskets are stronger for
that).
