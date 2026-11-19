const assert = require('node:assert/strict');
const test = require('node:test');
require('../moment_4417/cases.cjs');

const moment = require(process.env.QSMINER_MOMENT);
const format = moment.HTML5_FMT.WEEK;
test('t10', () => assert.equal(moment.utc('2020-06-15').format(format), '2020-W25'));
test('t11', () => assert.equal(moment.utc('2004-W01', format, true).format(format), '2004-W01'));
test('t12', () => assert.equal(moment.utc('2016-01-01').format(format), '2015-W53'));
test('t13', () => assert.equal(moment.utc('2018-12-31').format(format), '2019-W01'));
