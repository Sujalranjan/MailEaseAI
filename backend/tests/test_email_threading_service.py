from app.models import Email, EmailAccount, EmailThread, User
from app.services.email_threading_service import assign_thread


def make_account(db_session, email="user@example.com"):
    user = User(email=email)
    db_session.add(user)
    db_session.flush()
    account = EmailAccount(user_id=user.id, email_address=email, provider="imap")
    db_session.add(account)
    db_session.flush()
    return account


def make_email(db_session, account, message_id, subject="Hi", in_reply_to=None, references=None):
    email = Email(
        email_account_id=account.id,
        provider_message_id=message_id,
        subject=subject,
        body="",
        in_reply_to=in_reply_to,
        references_header=references,
    )
    db_session.add(email)
    db_session.flush()
    return email


class TestNewRootMessage:
    def test_message_with_no_threading_headers_gets_new_thread(self, db_session):
        account = make_account(db_session)
        email = make_email(db_session, account, "<root@example.com>")

        thread = assign_thread(db_session, account.id, email)

        assert email.thread_id == thread.id
        assert db_session.query(EmailThread).count() == 1
        assert thread.subject == "Hi"


class TestReplyThreading:
    def test_reply_via_in_reply_to_joins_parent_thread(self, db_session):
        account = make_account(db_session)
        root = make_email(db_session, account, "<root@example.com>")
        root_thread = assign_thread(db_session, account.id, root)

        reply = make_email(
            db_session, account, "<reply1@example.com>", subject="Re: Hi", in_reply_to="<root@example.com>"
        )
        reply_thread = assign_thread(db_session, account.id, reply)

        assert reply_thread.id == root_thread.id
        assert db_session.query(EmailThread).count() == 1

    def test_reply_via_references_joins_thread_even_without_in_reply_to(self, db_session):
        account = make_account(db_session)
        root = make_email(db_session, account, "<root2@example.com>")
        root_thread = assign_thread(db_session, account.id, root)

        reply = make_email(
            db_session,
            account,
            "<reply2@example.com>",
            references="<root2@example.com>",
        )
        reply_thread = assign_thread(db_session, account.id, reply)

        assert reply_thread.id == root_thread.id

    def test_multiple_replies_land_in_same_thread(self, db_session):
        account = make_account(db_session)
        root = make_email(db_session, account, "<root3@example.com>")
        assign_thread(db_session, account.id, root)

        reply1 = make_email(db_session, account, "<r3a@example.com>", in_reply_to="<root3@example.com>")
        t1 = assign_thread(db_session, account.id, reply1)

        reply2 = make_email(db_session, account, "<r3b@example.com>", in_reply_to="<root3@example.com>")
        t2 = assign_thread(db_session, account.id, reply2)

        reply3 = make_email(
            db_session,
            account,
            "<r3c@example.com>",
            in_reply_to="<r3a@example.com>",
            references="<root3@example.com> <r3a@example.com>",
        )
        t3 = assign_thread(db_session, account.id, reply3)

        assert t1.id == t2.id == t3.id
        assert db_session.query(EmailThread).count() == 1
        assert len(t1.emails) == 4


class TestOutOfOrderArrival:
    def test_reply_arriving_before_parent_gets_own_thread_then_merges(self, db_session):
        account = make_account(db_session)

        # Reply arrives first (parent not yet synced) — must not crash,
        # gets a provisional thread of its own.
        reply = make_email(db_session, account, "<child@example.com>", in_reply_to="<parent@example.com>")
        reply_thread = assign_thread(db_session, account.id, reply)
        assert db_session.query(EmailThread).count() == 1

        # Parent arrives later (e.g. next sync call) — forward search
        # must find the already-stored child and merge into one thread.
        parent = make_email(db_session, account, "<parent@example.com>")
        parent_thread = assign_thread(db_session, account.id, parent)

        db_session.refresh(reply)
        assert parent_thread.id == reply.thread_id
        assert db_session.query(EmailThread).count() == 1
        assert len(parent_thread.emails) == 2

    def test_grandchild_via_references_merges_when_grandparent_arrives_late(self, db_session):
        account = make_account(db_session)

        # child replies to a parent we've never seen, but also lists an
        # even older ancestor in References that we also haven't seen.
        child = make_email(
            db_session,
            account,
            "<gc-child@example.com>",
            in_reply_to="<gc-parent@example.com>",
            references="<gc-grandparent@example.com> <gc-parent@example.com>",
        )
        assign_thread(db_session, account.id, child)
        assert db_session.query(EmailThread).count() == 1

        # The grandparent (not the direct parent) turns up later. It's
        # only reachable via the References scan, not an In-Reply-To
        # exact match, since child's In-Reply-To points at gc-parent.
        grandparent = make_email(db_session, account, "<gc-grandparent@example.com>")
        thread = assign_thread(db_session, account.id, grandparent)

        db_session.refresh(child)
        assert child.thread_id == thread.id
        assert db_session.query(EmailThread).count() == 1


class TestMissingAndMalformedHeaders:
    def test_missing_headers_does_not_crash(self, db_session):
        account = make_account(db_session)
        email = make_email(db_session, account, "<no-headers@example.com>", in_reply_to=None, references=None)

        thread = assign_thread(db_session, account.id, email)

        assert thread is not None
        assert email.thread_id == thread.id

    def test_malformed_in_reply_to_without_brackets_is_ignored_gracefully(self, db_session):
        account = make_account(db_session)
        email = make_email(
            db_session, account, "<malformed@example.com>", in_reply_to="not-a-valid-message-id-no-brackets"
        )

        thread = assign_thread(db_session, account.id, email)

        assert thread is not None
        assert db_session.query(EmailThread).count() == 1

    def test_malformed_references_mixed_with_valid_ids(self, db_session):
        account = make_account(db_session)
        root = make_email(db_session, account, "<mixed-root@example.com>")
        root_thread = assign_thread(db_session, account.id, root)

        reply = make_email(
            db_session,
            account,
            "<mixed-reply@example.com>",
            references="garbage-not-an-id <mixed-root@example.com> another-garbage-token",
        )
        thread = assign_thread(db_session, account.id, reply)

        assert thread.id == root_thread.id


class TestDuplicateSyncIdempotency:
    def test_reassigning_same_email_object_again_does_not_create_extra_thread(self, db_session):
        account = make_account(db_session)
        root = make_email(db_session, account, "<idem-root@example.com>")
        thread1 = assign_thread(db_session, account.id, root)
        thread2 = assign_thread(db_session, account.id, root)

        assert thread1.id == thread2.id
        assert db_session.query(EmailThread).count() == 1


class TestNoFalseMerging:
    def test_unrelated_emails_with_same_subject_stay_in_separate_threads(self, db_session):
        account = make_account(db_session)
        email_a = make_email(db_session, account, "<subjA@example.com>", subject="Meeting")
        email_b = make_email(db_session, account, "<subjB@example.com>", subject="Meeting")

        thread_a = assign_thread(db_session, account.id, email_a)
        thread_b = assign_thread(db_session, account.id, email_b)

        assert thread_a.id != thread_b.id
        assert db_session.query(EmailThread).count() == 2

    def test_reply_referencing_wrong_account_ancestor_does_not_join_it(self, db_session):
        account_a = make_account(db_session, email="a@example.com")
        account_b = make_account(db_session, email="b@example.com")

        root_a = make_email(db_session, account_a, "<shared-id@example.com>")
        thread_a = assign_thread(db_session, account_a.id, root_a)

        # Same Message-ID coincidentally exists on a different account —
        # must never be treated as evidence linking across accounts.
        root_b = make_email(db_session, account_b, "<shared-id@example.com>")
        reply_b = make_email(
            db_session, account_b, "<reply-b@example.com>", in_reply_to="<shared-id@example.com>"
        )
        assign_thread(db_session, account_b.id, root_b)
        thread_b = assign_thread(db_session, account_b.id, reply_b)

        assert thread_b.id != thread_a.id


class TestCrossAccountIsolation:
    def test_identical_reply_chains_on_two_accounts_produce_separate_threads(self, db_session):
        account_1 = make_account(db_session, email="one@example.com")
        account_2 = make_account(db_session, email="two@example.com")

        root_1 = make_email(db_session, account_1, "<root@example.com>")
        reply_1 = make_email(db_session, account_1, "<reply@example.com>", in_reply_to="<root@example.com>")
        root_2 = make_email(db_session, account_2, "<root@example.com>")
        reply_2 = make_email(db_session, account_2, "<reply@example.com>", in_reply_to="<root@example.com>")

        t_root_1 = assign_thread(db_session, account_1.id, root_1)
        t_reply_1 = assign_thread(db_session, account_1.id, reply_1)
        t_root_2 = assign_thread(db_session, account_2.id, root_2)
        t_reply_2 = assign_thread(db_session, account_2.id, reply_2)

        assert t_root_1.id == t_reply_1.id
        assert t_root_2.id == t_reply_2.id
        assert t_root_1.id != t_root_2.id
        assert db_session.query(EmailThread).count() == 2


class TestRelationshipsAndCascade:
    def test_thread_emails_relationship_ordered_by_received_at(self, db_session):
        from datetime import datetime, timedelta

        account = make_account(db_session)
        root = make_email(db_session, account, "<order-root@example.com>")
        root.received_at = datetime(2026, 1, 1)
        thread = assign_thread(db_session, account.id, root)

        reply = make_email(db_session, account, "<order-reply@example.com>", in_reply_to="<order-root@example.com>")
        reply.received_at = datetime(2026, 1, 1) + timedelta(days=1)
        assign_thread(db_session, account.id, reply)

        db_session.refresh(thread)
        assert [e.provider_message_id for e in thread.emails] == [
            "<order-root@example.com>",
            "<order-reply@example.com>",
        ]

    def test_deleting_an_email_does_not_delete_its_thread(self, db_session):
        account = make_account(db_session)
        root = make_email(db_session, account, "<del-root@example.com>")
        thread = assign_thread(db_session, account.id, root)
        thread_id = thread.id

        db_session.delete(root)
        db_session.commit()

        assert db_session.get(EmailThread, thread_id) is not None

    def test_single_provisional_thread_is_reused_not_recreated_when_parent_arrives(self, db_session):
        account = make_account(db_session)
        reply = make_email(db_session, account, "<merge-child@example.com>", in_reply_to="<merge-parent@example.com>")
        provisional_thread = assign_thread(db_session, account.id, reply)
        provisional_id = provisional_thread.id

        parent = make_email(db_session, account, "<merge-parent@example.com>")
        canonical_thread = assign_thread(db_session, account.id, parent)

        assert canonical_thread.id == provisional_id  # parent created no new thread; provisional becomes canonical
        assert db_session.query(EmailThread).count() == 1

    def test_merging_two_independently_populated_threads_reparents_all_members(self, db_session):
        account = make_account(db_session)

        # Thread A: m1 (root) <- m2 (reply)
        m1 = make_email(db_session, account, "<m1@example.com>")
        thread_a = assign_thread(db_session, account.id, m1)
        m2 = make_email(db_session, account, "<m2@example.com>", in_reply_to="<m1@example.com>")
        assign_thread(db_session, account.id, m2)

        # Thread B: m3 (root) <- m4 (reply) -- fully separate so far
        m3 = make_email(db_session, account, "<m3@example.com>")
        thread_b = assign_thread(db_session, account.id, m3)
        m4 = make_email(db_session, account, "<m4@example.com>", in_reply_to="<m3@example.com>")
        assign_thread(db_session, account.id, m4)

        assert thread_a.id != thread_b.id
        assert db_session.query(EmailThread).count() == 2
        non_canonical_id = max(thread_a.id, thread_b.id)

        # m5 proves A and B are actually one conversation: it replies to
        # m2 (in thread A) and also references m4 (in thread B).
        m5 = make_email(
            db_session,
            account,
            "<m5@example.com>",
            in_reply_to="<m2@example.com>",
            references="<m1@example.com> <m2@example.com> <m4@example.com>",
        )
        merged_thread = assign_thread(db_session, account.id, m5)

        assert db_session.query(EmailThread).count() == 1
        assert db_session.get(EmailThread, non_canonical_id) is None  # deleted, not just abandoned
        all_message_ids = {e.provider_message_id for e in merged_thread.emails}
        assert all_message_ids == {
            "<m1@example.com>",
            "<m2@example.com>",
            "<m3@example.com>",
            "<m4@example.com>",
            "<m5@example.com>",
        }
