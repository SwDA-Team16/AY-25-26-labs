import payload from "mzinga";
import { PaginatedDocs } from "mzinga/database";
import { CollectionConfig, TypeWithID } from "mzinga/types";
import { AccessUtils } from "../utils";
import { CollectionUtils } from "../utils/CollectionUtils";
import { MailUtils } from "../utils/MailUtils";
import { MZingaLogger } from "../utils/MZingaLogger";
import { TextUtils } from "../utils/TextUtils";
import { Slugs } from "./Slugs";

const access = new AccessUtils();
const collectionUtils = new CollectionUtils(Slugs.Communications);
const Communications: CollectionConfig = {
  slug: Slugs.Communications,
  access: {
    read: access.GetIsAdmin,
    create: access.GetIsAdmin,
    delete: () => {
      return false;
    },
    update: () => {
      return false;
    },
  },
  admin: {
    ...collectionUtils.GeneratePreviewConfig(),
    useAsTitle: "subject",
    defaultColumns: ["subject", "status", "tos"], // [Lab 1 - Step 3.2] Expose delivery status to monitor async email processing (external worker pattern)
    group: "Notifications",
    disableDuplicate: true,
    enableRichTextRelationship: false,
  },

  // [Lab 1 - Step 2] afterChange hook triggered on document create/update to handle email workflow
  hooks: {
    afterChange: [
      async ({ doc }) => {
        const useExternalWorker =
          process.env.COMMUNICATIONS_EXTERNAL_WORKER === "true";

        // [Lab 1 - Step 4.2] Prevent infinite loop when payload.update retriggers afterChange
        if (doc.status === "pending" || doc.status === "sent") {
          return doc;
        }

        // --- New behavior: delegate delivery to the external worker ---
        // [Lab 1 - Step 4.2]  Branch by Abstraction: switch from synchronous email sending
        // to external worker model using a feature flag
        if (useExternalWorker) {

          await payload.update({
            collection: Slugs.Communications,
            id: doc.id,
            data: {
              status: "pending",
            },
          });

          return doc;
        }

        // --- Legacy behavior: synchronous in-process email delivery ---
        const { tos, ccs, bccs, subject, body } = doc;

        // [Lab 1 - Step 2.1.1] Resolve upload references in the rich-text body before serialization
        for (const part of body) {
          if (part.type !== "upload") {
            continue;
          }

          const relationToSlug = part.relationTo;
          const uploadedDoc = await payload.findByID({
            collection: relationToSlug,
            id: part.value.id,
          });

          part.value = {
            ...part.value,
            ...uploadedDoc,
          };
        }

        // [Lab 1 - Step 2.1.2] Serialize the body (Slate AST) to HTML for email rendering
        const html = TextUtils.Serialize(body || "");

        try {

          // [Lab 1 - Step 2.1.3] Resolve `tos` relationship references to actual recipient email addresses
          const users = await payload.find({
            collection: tos[0].relationTo,
            where: {
              id: {
                in: tos.map((to) => to.value.id || to.value).join(","),
              },
            },
          });

          const usersEmails = users.docs.map((u) => u.email);

          if (!usersEmails.length) {
            throw new Error("No valid email addresses found for 'tos' users.");
          }

          // [Lab 1 - Step 2.1.4] Resolve optional `ccs` and `bccs` relationship references
          let cc;
          if (ccs && ccs.length > 0) {
            const copiedusers = await payload.find({
              collection: ccs[0].relationTo,
              where: {
                id: {
                  in: ccs.map((cc) => cc.value.id || cc.value).join(","),
                },
              },
            });

            cc = copiedusers.docs.map((u) => u.email).join(",");
          }

          let bcc;
          if (bccs && bccs.length > 0) {
            const blindcopiedusers = await payload.find({
              collection: bccs[0].relationTo,
              where: {
                id: {
                  in: bccs.map((bcc) => bcc.value.id || bcc.value).join(","),
                },
              },
            });

            bcc = blindcopiedusers.docs.map((u) => u.email).join(",");
          }

          // [Lab 1 - Step 2.1.5] Build one email message per recipient and send them concurrently
          const promises = [];
          for (const to of usersEmails) {
            const message = {
              from: payload.emailOptions.fromAddress,
              subject,
              to,
              cc,
              bcc,
              html,
            };

            promises.push(
              MailUtils.sendMail(payload, message).catch((e) => {
                MZingaLogger.Instance?.error(`[Communications:err] ${e}`);
                return null;
              }),
            );
          }

          // [Lab 1 - Step 2.1] The request remains blocked until all email send operations complete
          await Promise.all(promises.filter((p) => Boolean(p)));

          await payload.update({
            collection: Slugs.Communications,
            id: doc.id,
            data: {
              status: "sent",
            },
          });

          return doc;

        } catch (err) {
          if (err.response && err.response.body && err.response.body.errors) {
            err.response.body.errors.forEach((error) =>
              MZingaLogger.Instance?.error(
                `[Communications:err]
                ${error.field}
                ${error.message}`,
              ),
            );
          } else {
            MZingaLogger.Instance?.error(`[Communications:err] ${err}`);
          }

          throw err;
        }
      },
    ],
  },
  fields: [
    {
      name: "subject",
      type: "text",
      required: true,
    },
    {
      // [Lab 1 - Step 3.1, Step 3.2] Delivery status used by the external worker lifecycle (pending -> processing -> sent/failed)
      name: "status",
      type: "select",
      options: [
        {
          label: "pending",
          value: "pending",
        },
        {
          label: "processing",
          value: "processing",
        },
        {
          label: "sent",
          value: "sent",
        },
        {
          label: "failed",
          value: "failed",
        },
      ],
      admin: {
        readOnly: true,
        position: "sidebar",
      },
    },
    {
      name: "tos",
      type: "relationship",
      relationTo: [Slugs.Users],
      required: true,
      hasMany: true,
      validate: (value, { data }) => {
        if (!value && data.sendToAll) {
          return true;
        }
        if (value) {
          return true;
        }
        return "No to(s) or sendToAll have been selected";
      },
      admin: {
        isSortable: true,
      },
      hooks: {
        beforeValidate: [
          async ({ value, data }) => {
            if (data.sendToAll) {
              const promises = [] as Promise<
                PaginatedDocs<Record<string, unknown> & TypeWithID>
              >[];

              const firstSetOfUsers = await payload.find({
                collection: Slugs.Users,
                limit: 100,
              });
              const pages = firstSetOfUsers.totalPages;
              for (let i = 1; i < pages; i++) {
                promises.push(
                  payload.find({
                    collection: Slugs.Users,
                    limit: 100,
                    page: i,
                  }),
                );
              }
              const allDocs = [firstSetOfUsers]
                .concat(await Promise.all(promises))
                .map((p) => p.docs)
                .flat()
                .map((d) => {
                  return { relationTo: Slugs.Users, value: d.id };
                });
              value = allDocs;
            }
            return value;
          },
        ],
      },
    },
    {
      name: "sendToAll",
      type: "checkbox",
      label: "Send to all users?",
    },
    {
      name: "ccs",
      type: "relationship",
      relationTo: [Slugs.Users],
      required: false,
      hasMany: true,
      admin: {
        isSortable: true,
      },
    },
    {
      name: "bccs",
      type: "relationship",
      relationTo: [Slugs.Users],
      required: false,
      hasMany: true,
      admin: {
        isSortable: true,
      },
    },
    {
      name: "body",
      type: "richText",
      required: true,
    },
  ],
};

export default Communications;
