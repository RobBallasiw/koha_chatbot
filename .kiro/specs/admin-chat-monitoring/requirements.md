# Requirements Document

## Introduction

The Admin Chat Monitoring feature adds a staff-facing dashboard to the Library AI Chatbot that allows library administrators and staff to monitor conversations between the chatbot and patrons. Staff can view active and past chat sessions, review patron questions and chatbot responses, and gain insight into chatbot usage patterns. The dashboard integrates with the existing FastAPI backend and is accessible through the Koha staff interface or a dedicated admin route.

## Glossary

- **Admin_Dashboard**: The staff-facing web interface that displays chat session data for monitoring purposes
- **Staff_User**: A library administrator or staff member who accesses the Admin_Dashboard to review chatbot conversations
- **Chat_Session**: A single conversation between a patron and the Chatbot, identified by a unique session ID and containing a sequence of messages
- **Session_Store**: The persistent storage layer that retains chat session data beyond the in-memory session lifetime for historical review
- **Backend**: The existing Python (FastAPI) server that orchestrates the chatbot and now also serves admin monitoring endpoints
- **Chatbot**: The conversational AI assistant that processes patron queries
- **Patron**: A library user interacting with the Chatbot through the OPAC
- **Session_Status**: The current state of a Chat_Session, either "active" (has exchanged messages within the timeout window) or "expired" (inactive beyond the timeout threshold)
- **Admin_API**: The set of REST API endpoints on the Backend that serve chat session data to the Admin_Dashboard

## Requirements

### Requirement 1: Persistent Chat Session Storage

**User Story:** As a staff user, I want chat sessions to be stored persistently, so that I can review conversations even after the in-memory session has expired.

#### Acceptance Criteria

1. WHEN a patron sends a message, THE Backend SHALL persist the message and the corresponding chatbot response to the Session_Store
2. THE Session_Store SHALL retain each Chat_Session record including the session ID, all messages with timestamps, session creation time, and last activity time
3. THE Session_Store SHALL retain chat session data independently of the in-memory session expiration
4. WHEN a Chat_Session is persisted, THE Session_Store SHALL record each message with its role (patron or assistant) and a timestamp
5. IF the Session_Store is unavailable, THEN THE Backend SHALL log the error and continue serving patron chat requests without interruption

### Requirement 2: Admin Dashboard — Session List View

**User Story:** As a staff user, I want to see a list of all chat sessions, so that I can browse conversations and identify sessions that need attention.

#### Acceptance Criteria

1. WHEN a Staff_User opens the Admin_Dashboard, THE Admin_Dashboard SHALL display a paginated list of Chat_Sessions ordered by most recent activity
2. THE Admin_Dashboard SHALL display the session ID, start time, last activity time, message count, and Session_Status for each Chat_Session in the list
3. WHEN a Staff_User selects a Chat_Session from the list, THE Admin_Dashboard SHALL navigate to the session detail view for that session
4. THE Admin_Dashboard SHALL allow the Staff_User to filter sessions by Session_Status (active or expired)
5. THE Admin_Dashboard SHALL allow the Staff_User to search sessions by keyword appearing in message content

### Requirement 3: Admin Dashboard — Session Detail View

**User Story:** As a staff user, I want to view the full conversation transcript of a chat session, so that I can review what the patron asked and how the chatbot responded.

#### Acceptance Criteria

1. WHEN a Staff_User views a Chat_Session detail, THE Admin_Dashboard SHALL display all messages in chronological order with the sender role and timestamp
2. THE Admin_Dashboard SHALL visually distinguish patron messages from chatbot responses using different styling
3. WHEN a Chat_Session is still active, THE Admin_Dashboard SHALL indicate the active status in the detail view
4. THE Admin_Dashboard SHALL display the session metadata including session ID, creation time, last activity time, and total message count

### Requirement 4: Admin API Endpoints

**User Story:** As a developer, I want the backend to expose REST API endpoints for retrieving chat session data, so that the admin dashboard can fetch monitoring data.

#### Acceptance Criteria

1. THE Admin_API SHALL expose a GET endpoint that returns a paginated list of Chat_Sessions with summary metadata
2. THE Admin_API SHALL accept query parameters for pagination (page number, page size), status filtering, and keyword search
3. THE Admin_API SHALL expose a GET endpoint that returns the full message history and metadata for a single Chat_Session identified by session ID
4. IF a requested Chat_Session does not exist, THEN THE Admin_API SHALL return a 404 status code with a descriptive error message
5. THE Admin_API SHALL return responses in JSON format

### Requirement 5: Admin Authentication and Access Control

**User Story:** As a library administrator, I want the admin dashboard to be protected by authentication, so that only authorized staff can view patron conversations.

#### Acceptance Criteria

1. WHEN an unauthenticated request is made to the Admin_API, THE Backend SHALL return a 401 status code
2. THE Backend SHALL authenticate Staff_Users using a shared API key passed in the request header
3. THE Admin_Dashboard SHALL include the API key in all requests to the Admin_API
4. THE Backend SHALL read the admin API key from an environment variable rather than a hardcoded value
5. IF an invalid API key is provided, THEN THE Backend SHALL return a 401 status code with a descriptive error message

### Requirement 6: Session Statistics Summary

**User Story:** As a staff user, I want to see summary statistics about chatbot usage, so that I can understand how patrons are using the chatbot.

#### Acceptance Criteria

1. THE Admin_API SHALL expose a GET endpoint that returns aggregate session statistics
2. THE Admin_API SHALL include the total number of sessions, total number of messages, count of active sessions, and count of expired sessions in the statistics response
3. WHEN a Staff_User opens the Admin_Dashboard, THE Admin_Dashboard SHALL display the session statistics summary on the main page

### Requirement 7: Admin Dashboard Frontend

**User Story:** As a staff user, I want a clean and usable web interface for monitoring, so that I can efficiently review chatbot conversations.

#### Acceptance Criteria

1. THE Admin_Dashboard SHALL be served as a static HTML page by the Backend at a dedicated admin route
2. THE Admin_Dashboard SHALL be usable on desktop screen sizes
3. THE Admin_Dashboard SHALL use semantic HTML and provide accessible labels for interactive elements
4. THE Admin_Dashboard SHALL display loading indicators while fetching data from the Admin_API
5. IF the Admin_API returns an error, THEN THE Admin_Dashboard SHALL display a user-friendly error message
