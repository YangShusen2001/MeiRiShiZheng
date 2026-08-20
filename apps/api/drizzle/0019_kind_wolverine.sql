CREATE TABLE `review_cards` (
	`owner_id` text NOT NULL,
	`card_id` text NOT NULL,
	`fsrs_state` text NOT NULL,
	`due_at` integer NOT NULL,
	`review_count` integer DEFAULT 0 NOT NULL,
	`last_review_at` integer,
	`created_at` integer NOT NULL,
	PRIMARY KEY(`owner_id`, `card_id`)
);
--> statement-breakpoint
CREATE INDEX `review_cards_owner_due_idx` ON `review_cards` (`owner_id`,`due_at`);