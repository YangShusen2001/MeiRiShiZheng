CREATE TABLE `notification_settings` (
	`owner_id` text PRIMARY KEY NOT NULL,
	`daily_enabled` integer DEFAULT false NOT NULL,
	`daily_at` text DEFAULT '08:30' NOT NULL,
	`review_enabled` integer DEFAULT false NOT NULL,
	`review_at` text DEFAULT '09:00' NOT NULL,
	`quota_enabled` integer DEFAULT false NOT NULL,
	`updated_at` integer NOT NULL
);
