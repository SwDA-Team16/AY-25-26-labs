import { Payload } from "mzinga";
import { MZingaLogger } from "../utils/MZingaLogger";

export class MailUtils {
  static async sendMail(payload: Payload, message: any) {

    // [Lab 1 - Step 2.2] Debug flag: when enabled, logs email payload instead of sending it
    if (process.env.DEBUG_EMAIL_SEND === "1") {
      MZingaLogger.Instance?.info(
        "[MailUtils:message] %s",
        JSON.stringify(message, null, 2),
      );
    }

    const email = await payload.email;
    const result = await email.transport.sendMail(message);

    if (process.env.DEBUG_EMAIL_SEND === "1") {
      MZingaLogger.Instance?.info(
        "[MailUtils:result] %s",
        JSON.stringify(result, null, 2),
      );
    }
    return result;
  }
}
