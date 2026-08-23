"""initial schema

Revision ID: 6131caf88720
Revises: 
Create Date: 2026-08-23 02:21:28.182076
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '6131caf88720'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initial schema. Squashed from the earlier German-named migrations before
    # the first commit — a rename history from day zero helps nobody.
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('default_plan_created', sa.Boolean(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('planner_blocks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('weekday', sa.String(length=3), nullable=False),
    sa.Column('time', sa.String(length=5), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('planner_blocks', schema=None) as batch_op:
        batch_op.create_index('ix_blocks_user_weekday', ['user_id', 'weekday'], unique=False)
        batch_op.create_index(batch_op.f('ix_planner_blocks_user_id'), ['user_id'], unique=False)

    op.create_table('planner_todos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('weekday', sa.String(length=3), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('planner_todos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_planner_todos_user_id'), ['user_id'], unique=False)
        batch_op.create_index('ix_todos_user_weekday', ['user_id', 'weekday'], unique=False)

    op.create_table('planner_block_completions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('block_id', sa.Integer(), nullable=False),
    sa.Column('completed_on', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['block_id'], ['planner_blocks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('block_id', 'completed_on', name='uq_block_completion')
    )
    with op.batch_alter_table('planner_block_completions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_planner_block_completions_block_id'), ['block_id'], unique=False)

    op.create_table('planner_todo_completions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('todo_id', sa.Integer(), nullable=False),
    sa.Column('completed_on', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['todo_id'], ['planner_todos.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('todo_id', 'completed_on', name='uq_todo_completion')
    )
    with op.batch_alter_table('planner_todo_completions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_planner_todo_completions_todo_id'), ['todo_id'], unique=False)

    # ### end Alembic commands ###


def downgrade() -> None:
    # Initial schema. Squashed from the earlier German-named migrations before
    # the first commit — a rename history from day zero helps nobody.
    with op.batch_alter_table('planner_todo_completions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_planner_todo_completions_todo_id'))

    op.drop_table('planner_todo_completions')
    with op.batch_alter_table('planner_block_completions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_planner_block_completions_block_id'))

    op.drop_table('planner_block_completions')
    with op.batch_alter_table('planner_todos', schema=None) as batch_op:
        batch_op.drop_index('ix_todos_user_weekday')
        batch_op.drop_index(batch_op.f('ix_planner_todos_user_id'))

    op.drop_table('planner_todos')
    with op.batch_alter_table('planner_blocks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_planner_blocks_user_id'))
        batch_op.drop_index('ix_blocks_user_weekday')

    op.drop_table('planner_blocks')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))

    op.drop_table('users')
    # ### end Alembic commands ###
