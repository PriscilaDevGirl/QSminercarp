const assert = require('node:assert/strict');
const test = require('node:test');
const moment = require(process.env.QSMINER_MOMENT);

const first = () => moment.utc('2018-05-01');
const middle = () => moment.utc('2018-05-12');
const last = () => moment.utc('2018-05-31');

test('t01', () => assert.equal(middle().format('YYYY-MM-DD'), '2018-05-12'));
test('t02', () => assert.equal(first().isBetween(first(), last()), false));
test('t03', () => assert.equal(first().isBetween(first(), last(), 'day', '[)'), true));
test('t04', () => assert.equal(middle().add(1, 'day').date(), 13));
test('t05', () => assert.equal(moment.invalid().isBetween(first(), last(), 'day', '[]'), false));
test('t06', () => assert.equal(middle().isBetween(first(), last(), 'day', '[]'), true));
test('t07', () => assert.equal(moment.duration(2, 'days').asHours(), 48));
test('t08', () => assert.equal(middle().isBetween(moment.invalid(), last(), 'day', '[]'), false));
test('t09', () => assert.equal(middle().isBetween(first(), moment.invalid(), 'day', '[]'), false));
