**Task: Build an OTP-Based Authentication System**

**Objective**

Design and implement a **complete authentication system** for a mobile-first application where users authenticate using their **phone number and OTP (One-Time Password)**.

You are expected to **decide the API structure, endpoints, and flow yoursel**

**Functional Requirements**

Your system must support the following flows:

**1. User Registration (Signup)**

- A user should be able to register using: 

  - Phone number (with country code) 

  - Optional details like name and email 

- Registration must require **OTP verification** 

- A user **must not be created without successful OTP verification** 



**2. OTP System**

- Generate a **numeric OTP (e.g., 4–6 digits)** 

- OTP should: 

  - Expire after a fixed time (e.g., 5 minutes) 

  - Be usable only once 

- Store OTP securely in the database 

- Validate OTP correctly before allowing authentication 



**3. User Login**

- Users should be able to log in using: 

  - Phone number + OTP 

- No password-based login required 

- On successful login: 

  - Generate an **authentication token (JWT or similar)** 



**4. Authenticated User Access**

- Provide a way to fetch the **currently logged-in user’s details** 

- This should require a valid authentication token 



**5. Health Check**

- Provide a simple way to verify that the backend service is running 

**Data Requirements**

Design appropriate database tables for:

**User**

- Basic profile details 

- Phone number (must be unique) 

- Verification status 

- Active status 

- Timestamps 

**OTP / Verification System**

- Phone number 

- OTP code 

- Expiry time 

- Usage status (used / unused) 

## Timestamps 



**Technical Requirements**

**Backend**

- Use **FastAPI** 

- Use an ORM (SQLAlchemy recommended) 

- Use a relational database (PostgreSQL/MySQL) 



**Authentication**

- Implement token-based authentication (JWT recommended) 

- Tokens must have an expiry time 



**Validation & Logic**

- Prevent duplicate users with the same phone number 

- Do not allow login/signup without valid OTP 

- Handle invalid and expired OTP cases properly 



**Security Requirements**

- Do not expose sensitive data 

- Use environment variables for secrets 

- Ensure OTP cannot be reused 

- Protect authenticated routes 



**Testing**

You must test:

- Valid and invalid OTP flows 

- Expired OTP cases 

- Duplicate user registration 

- Unauthorized access to protected routes 

**Code Structure**

Organize your project cleanly into:

- Models 

- Schemas 

- Services / Business logic 

- API routes 

- Config / Security 

