# Official List

### Tool that Maintains a List of all US Senators and Representatives

The Official List is a Kubernetes microservice designed to keep an updated record of all US Senators and Representatives. It utilizes Kubernetes components, including a stateful PostgreSQL instance, to check for daily changes in the list of existing members in the House and Senate. Any new members detected are added to the statefulset, ensuring an accurate and up-to-date representation of the legislative body.

## Functionality

The microservice performs the following tasks:

- **Daily Member Check:**
  - Retrieves the current list of members from the House and Senate.
  - Compares it with the list from the previous recording.
  
- **Database Management:**
  - Writes the daily member list to a stateful PostgreSQL instance in Kubernetes.
  - Updates the statefulset by adding new members if a diff exists.

## Background

The primary motivation behind maintaining this list is to facilitate the tracking of recent stock trades made by legislators. This information is crucial for copy trading, where another microservice iterates through the list and scrapes congressional stock trading disclosure data by member [Official Disclosure Service](https://github.com/Travbz/official-disclosures). The scraped data is stored in a database, and the microservice looks for differences between previously known disclosures and new data.

If new data is detected, it signifies that a trade has been placed, triggering a payload to be sent to the notification service. The notification service alerts users about new disclosures, allowing them to take necessary actions.

## Future Development

We have plans to expand the functionality of the suite of services related to legislative activities. Future enhancements may include:

- **Keyword-based Legislation Scanning:**
  - Scanning legislation for keywords related to ticker symbols.
  - Predicting potential legislative outcomes based on congressional stock trade activity.

## Contribution

If you are interested in contributing to the development of these services or have ideas for improvement, please let us know! Your collaboration is welcomed and appreciated.

