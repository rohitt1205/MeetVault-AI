DUMMY_MEETING_TRANSCRIPT = """
Meeting Title: Q3 Product Roadmap Alignment
Date: October 15, 2026
Attendees: Alice (Product Manager), Bob (Engineering Lead), Charlie (UX Designer)

Alice: Alright everyone, let's kick off. The main goal today is to finalize our Q3 product roadmap. First item on the agenda is the new user onboarding flow. Charlie, do we have the final designs?

Charlie: Yes, the designs are ready. We've simplified the sign-up process from 5 steps down to 3. We removed the mandatory phone number verification, which should increase our conversion rate. The Figma link is in the team channel.

Bob: That's great, but from an engineering perspective, if we remove phone verification, we need to implement reCAPTCHA to prevent bot spam. I estimate that will take about an extra week of development time.

Alice: Understood. Let's add reCAPTCHA to the sprint. Bob, can you make sure a Jira ticket is created for that?

Bob: Will do. I'll assign it to Sarah.

Alice: Perfect. Next up is the dark mode feature. We've had a lot of user requests for this.

Charlie: We have the color palette defined, but I haven't finished mapping all the CSS variables yet. I'll need another two days to wrap that up.

Bob: We can't start the frontend work until those variables are mapped. If you get it done by Wednesday, we can start implementation on Thursday.

Alice: Okay, action item for Charlie: finish the CSS variables by Wednesday. Action item for Bob: schedule the frontend team to start dark mode on Thursday. 

Bob: Also, a quick note on infrastructure. We need to upgrade our database instance before the end of the month because we are hitting our connection limits during peak hours.

Alice: Good point. Is there any downtime expected?

Bob: Yes, about 30 minutes. We should schedule it for a Sunday at 2 AM to minimize impact. I'll draft an email to the customers giving them a 48-hour heads up.

Alice: Excellent. So to summarize:
1. We are proceeding with the 3-step onboarding and adding reCAPTCHA. Bob will create the ticket.
2. Dark mode CSS will be finalized by Wednesday, frontend work starts Thursday.
3. Database upgrade is scheduled for Sunday at 2 AM. Bob will notify customers.

Are we all aligned?

Charlie: Aligned.
Bob: Sounds good.

Alice: Great, meeting adjourned.
"""
