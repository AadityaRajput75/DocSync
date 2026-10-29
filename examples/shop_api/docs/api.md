# Shop API

## list_products
GET `/products` lists product identifiers. The `limit` parameter defaults to 10.

## create_order
POST `/orders` calls `create_order()` with a quantity default of 1. Each item costs ten units; pricing is calculated by `calculate_total()`.

## cancel_order
DELETE `/orders/{order_id}` returns the order identifier and `cancelled: true`.

## Deployment
This guide was reviewed by the shop team. Keep deployment configuration outside the repository.
