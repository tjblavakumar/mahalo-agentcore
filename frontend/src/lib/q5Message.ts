/**
 * The single fixed "Q5" message shown for any unrenderable viz reply or /chat
 * error (design §5.1). Shared so the dashboard chat box and the idea strip's
 * click-to-build glue use one copy of the text.
 */
export const Q5_MESSAGE =
  "I can only build charts and tables here. I couldn't turn that into a line, area, or bar " +
  "chart or a table. For general or text answers, use the Chat screen. Try asking for a metric " +
  "over a dimension, e.g. 'story points by sprint for PAY' or 'open PRs by project'.";
