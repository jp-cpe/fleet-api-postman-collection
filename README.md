# Fleet API Postman Collection

This repository contains a comprehensive Postman collection for the Fleet API (version 4.7.0). The collection was created based on the [official Fleet REST API documentation](https://fleetdm.com/docs/rest-api/rest-api#rest-api).

### Features:

* **Comprehensive Coverage**: Includes nearly all available API endpoints.
* **Parameter Inclusion**: Contains all supported parameters with clear examples provided whenever possible.
* **Validated Endpoints**: Approximately 90% of endpoints have been thoroughly tested and validated.

### Setup & Usage:

1. **Import the Collection**: Import the collection into Postman.
2. **Create a New Environment**:

   * Name the environment `Fleet`.
   * Tie it to the imported collection.
3. **Configure Environment Variables**:

   * Add the following required variables:

     * `baseUrl`
     * `email`
     * `password`
   * The `token` variable will automatically populate upon initial authentication, though you can manually set a different token if desired.

### Recommendations:

* Always test requests against a **development environment** before using them in production.
* Review endpoints and parameters carefully before execution to ensure correctness.

### Contributing:

If you discover any issues or identify areas for improvement, please open a pull request. Contributions and feedback are always welcome!

### Documentation:

* [Fleet REST API Documentation](https://fleetdm.com/docs/rest-api/rest-api#rest-api)

Thank you for contributing to the improvement of this collection!
