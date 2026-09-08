-- 0007_account_deletion — trace de conformité RGPD/CCPA (WP10).
-- eBay envoie une notification par utilisateur qui ferme son compte. On garde
-- une trace *sans donnée personnelle* : de quoi prouver le traitement et rendre
-- la réception idempotente (eBay réémet la même notification jusqu'à ~24 h).
-- Le `username` reçu n'est JAMAIS persisté ici : le but de la notification est
-- justement de l'effacer.

CREATE TABLE account_deletion_events (
  notification_id  TEXT    PRIMARY KEY,   -- notification.notificationId, dédoublonnage
  received_at      TEXT    NOT NULL,      -- ISO 8601 UTC
  scrubbed_rows    INTEGER NOT NULL       -- lignes `listings` anonymisées
);
