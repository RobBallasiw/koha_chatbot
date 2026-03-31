# Requirements Document

## Introduction

The Library AI Chatbot is a conversational assistant embedded in the Koha OPAC that helps library patrons search the catalog, check book availability, and get answers about library hours, policies, and fines. It uses a Python backend (Flask/FastAPI), a Groq LLM API (Llama 3) for natural language understanding, and the Koha REST API for live catalog data. The frontend is a lightweight chat widget embedded via iframe in the Koha patron-facing interface.

## Glossary

- **Chatbot**: The conversational AI assistant that processes patron queries and returns responses
- **OPAC**: Online Public Access Catalog — the patron-facing interface of the Koha library system
- **Koha_API**: The Koha ILS REST API used to retrieve catalog records, item availability, and patron-facing data
- **Groq_API**: The Groq Cloud LLM API providing Llama 3 inference for natural language processing
- **Chat_Widget**: The frontend UI component embedded in the Koha OPAC that provides the chat interface
- **Backend**: The Python (Flask/FastAPI) server that orchestrates communication between the Chat_Widget, Groq_API, and Koha_API
- **Catalog_Record**: A bibliographic record in the Koha system representing a book or other library item
- **Patron**: A library user interacting with the Chatbot through the OPAC
- **Library_Info_Store**: A local data source containing library-specific information such as hours, policies, and fine schedules
- **Query_Classifier**: The component within the Backend that determines whether a patron query is a catalog search or a general library information question

## Requirements

### Requirement 1: Catalog Search via Natural Language

**User Story:** As a patron, I want to search the library catalog using natural language, so that I can find books without needing to know exact titles or use advanced search syntax.

#### Acceptance Criteria

1. WHEN a patron submits a natural language search query, THE Backend SHALL extract search parameters (title, author, subject, ISBN) from the query using the Groq_API
2. WHEN search parameters are extracted, THE Backend SHALL query the Koha_API and return matching Catalog_Records to the Chat_Widget
3. WHEN matching Catalog_Records are found, THE Chatbot SHALL present the results in a readable format including title, author, and call number
4. WHEN no matching Catalog_Records are found, THE Chatbot SHALL inform the patron that no results were found and suggest refining the search
5. IF the Koha_API is unreachable, THEN THE Backend SHALL return an error message indicating the catalog is temporarily unavailable

### Requirement 2: Book Availability Check

**User Story:** As a patron, I want to check whether a specific book is available, so that I can decide whether to visit the library.

#### Acceptance Criteria

1. WHEN a patron asks about the availability of a specific item, THE Backend SHALL query the Koha_API for the item's availability status
2. WHEN the item is available, THE Chatbot SHALL respond with the item location, branch, and call number
3. WHEN the item is checked out, THE Chatbot SHALL respond with the expected return date if available
4. WHEN multiple copies of the item exist, THE Chatbot SHALL list the availability status of each copy grouped by branch
5. IF the Koha_API returns an error for the availability request, THEN THE Backend SHALL inform the patron that availability information is temporarily unavailable

### Requirement 3: Library Information Queries

**User Story:** As a patron, I want to ask questions about library hours, policies, and fines, so that I can get quick answers without navigating the library website.

#### Acceptance Criteria

1. WHEN a patron asks about library hours, THE Chatbot SHALL respond with the current operating hours from the Library_Info_Store
2. WHEN a patron asks about library policies (borrowing limits, renewal rules, membership), THE Chatbot SHALL respond with the relevant policy information from the Library_Info_Store
3. WHEN a patron asks about fines or fees, THE Chatbot SHALL respond with the applicable fine schedule from the Library_Info_Store
4. WHEN the Library_Info_Store does not contain information relevant to the patron's question, THE Chatbot SHALL inform the patron that the information is not available and suggest contacting library staff
5. THE Library_Info_Store SHALL be configurable by library administrators without requiring code changes

### Requirement 4: Query Classification

**User Story:** As a patron, I want the chatbot to understand my intent automatically, so that I get the right type of response without specifying whether I want a catalog search or general information.

#### Acceptance Criteria

1. WHEN a patron submits a message, THE Query_Classifier SHALL classify the query as either a catalog search or a library information question
2. WHEN a query is classified as a catalog search, THE Backend SHALL route the query to the catalog search flow
3. WHEN a query is classified as a library information question, THE Backend SHALL route the query to the library information flow
4. WHEN the Query_Classifier cannot determine the intent with sufficient confidence, THE Chatbot SHALL ask the patron a clarifying question
5. THE Query_Classifier SHALL use the Groq_API to perform intent classification

### Requirement 5: Chat Widget Embedding

**User Story:** As a library administrator, I want to embed the chatbot in the Koha OPAC, so that patrons can access it directly from the catalog interface.

#### Acceptance Criteria

1. THE Chat_Widget SHALL be embeddable in the Koha OPAC via an iframe or JavaScript snippet
2. THE Chat_Widget SHALL provide a text input field and a scrollable message history area
3. THE Chat_Widget SHALL display patron messages and Chatbot responses in a conversational thread format
4. THE Chat_Widget SHALL be responsive and usable on both desktop and mobile screen sizes
5. WHEN the Backend is unreachable, THE Chat_Widget SHALL display a message indicating the chatbot is temporarily unavailable

### Requirement 6: Conversation Context Management

**User Story:** As a patron, I want the chatbot to remember context within a conversation, so that I can ask follow-up questions without repeating myself.

#### Acceptance Criteria

1. WHILE a chat session is active, THE Backend SHALL maintain conversation history for the session
2. WHEN a patron sends a follow-up message, THE Backend SHALL include relevant conversation history when calling the Groq_API
3. WHEN a chat session has been inactive for more than 30 minutes, THE Backend SHALL clear the session's conversation history
4. THE Backend SHALL limit conversation history to the most recent 20 messages per session to control Groq_API token usage
5. WHEN a new chat session starts, THE Backend SHALL initialize an empty conversation history

### Requirement 7: Groq LLM Integration

**User Story:** As a developer, I want the backend to integrate with the Groq Cloud API using Llama 3, so that the chatbot can generate natural language responses.

#### Acceptance Criteria

1. THE Backend SHALL send prompts to the Groq_API using the Llama 3 model for all natural language processing tasks
2. THE Backend SHALL include a system prompt that constrains the Chatbot to library-related topics only
3. IF the Groq_API returns an error or times out, THEN THE Backend SHALL return a graceful fallback message to the patron
4. THE Backend SHALL enforce a maximum response token limit to control API costs
5. IF the Groq_API rate limit is exceeded, THEN THE Backend SHALL queue the request and inform the patron of a brief delay

### Requirement 8: API Request and Response Handling

**User Story:** As a developer, I want the backend to expose a clean REST API for the chat widget, so that the frontend and backend communicate reliably.

#### Acceptance Criteria

1. THE Backend SHALL expose a POST endpoint that accepts a patron message and session identifier and returns a Chatbot response
2. THE Backend SHALL validate that incoming requests contain a non-empty message and a valid session identifier
3. IF a request is missing required fields, THEN THE Backend SHALL return a 400 status code with a descriptive error message
4. THE Backend SHALL return responses in JSON format containing the Chatbot reply text and a session identifier
5. THE Backend SHALL respond to chat requests within 10 seconds under normal operating conditions

### Requirement 9: Configuration and Deployment

**User Story:** As a developer, I want the application to be configurable via environment variables, so that it can be deployed across development (Windows) and production (Linux/Koha) environments without code changes.

#### Acceptance Criteria

1. THE Backend SHALL read all external service URLs (Koha_API base URL, Groq_API endpoint) from environment variables
2. THE Backend SHALL read API keys and secrets from environment variables rather than hardcoded values
3. THE Backend SHALL load Library_Info_Store data from a configurable file path specified via environment variable
4. THE Backend SHALL support running on both Windows and Linux operating systems without platform-specific code paths
5. IF a required environment variable is missing at startup, THEN THE Backend SHALL log a descriptive error and exit with a non-zero status code
